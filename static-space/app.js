/* Video to GIF, in the browser. ffmpeg.wasm (single thread) runs the same
   two-pass palette filter graph as vid2gif.py. Nothing is uploaded. */
(function () {
  "use strict";

  // Pinned CDN versions (see README). All are on npm for more than two weeks.
  // The ESM builds are used: the UMD build of @ffmpeg/util 0.12.2 throws
  // "exports is not defined" in a script tag, and the UMD worker cannot
  // import the core from a blob URL.
  var CDN = "https://cdn.jsdelivr.net/npm";
  var FFMPEG_DIR = CDN + "/@ffmpeg/ffmpeg@0.12.15/dist/esm/";
  var UTIL_ESM = CDN + "/@ffmpeg/util@0.12.2/dist/esm/index.js";
  var CORE_JS = CDN + "/@ffmpeg/core@0.12.10/dist/esm/ffmpeg-core.js";
  var CORE_WASM = CDN + "/@ffmpeg/core@0.12.10/dist/esm/ffmpeg-core.wasm";

  var MAX_BYTES = 200 * 1024 * 1024;
  var BIG_BYTES = 80 * 1024 * 1024;
  var MAX_SECONDS = 15;

  var $ = function (id) { return document.getElementById(id); };
  var els = {
    file: $("file"), drop: $("drop"), fileNote: $("fileNote"), editor: $("editor"),
    video: $("video"), videoMeta: $("videoMeta"), useTime: $("useTime"),
    form: $("form"), start: $("start"), duration: $("duration"),
    width: $("width"), widthOut: $("widthOut"), fps: $("fps"), fpsOut: $("fpsOut"),
    dither: $("dither"), loop: $("loop"), go: $("go"), cancel: $("cancel"),
    warn: $("warn"), progressBox: $("progressBox"), bar: $("bar"),
    progressText: $("progressText"), error: $("error"),
    result: $("result"), gif: $("gif"), gifMeta: $("gifMeta"), download: $("download")
  };

  var state = { file: null, videoURL: null, gifURL: null, ffmpeg: null, loaded: false, busy: false, cancelled: false };

  function show(el, on) { el.hidden = !on; }
  function setText(el, text) { el.textContent = text; }
  function fmtBytes(n) {
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(2) + " MB";
  }
  function fmtNum(x) { return String(Number(x.toFixed(3))); }

  function showError(msg) { setText(els.error, msg); show(els.error, true); }
  function clearError() { show(els.error, false); }

  function setProgress(ratio, text) {
    show(els.progressBox, true);
    var barBox = els.bar.parentNode;
    if (ratio == null) {
      barBox.classList.add("indeterminate");
      els.bar.style.width = "";
    } else {
      barBox.classList.remove("indeterminate");
      els.bar.style.width = Math.max(0, Math.min(100, ratio * 100)).toFixed(0) + "%";
    }
    setText(els.progressText, text);
  }

  // ---- loading the converter -------------------------------------------
  async function toBlobURL(url, mime) {
    var res = await fetch(url);
    if (!res.ok) throw new Error("Download failed (" + res.status + "): " + url);
    var buf = await res.arrayBuffer();
    return URL.createObjectURL(new Blob([buf], { type: mime }));
  }

  // A module Worker cannot be created from another origin, so the worker
  // script from the CDN is fetched and started from a blob URL. Its two
  // relative imports are pointed at blob URLs too.
  async function makeWorkerURL() {
    var texts = await Promise.all(["worker.js", "const.js", "errors.js"].map(function (f) {
      return fetch(FFMPEG_DIR + f).then(function (r) {
        if (!r.ok) throw new Error("Download failed (" + r.status + "): " + FFMPEG_DIR + f);
        return r.text();
      });
    }));
    var mk = function (t) { return URL.createObjectURL(new Blob([t], { type: "text/javascript" })); };
    var src = texts[0].replace("./const.js", mk(texts[1])).replace("./errors.js", mk(texts[2]));
    return mk(src);
  }

  async function ensureFFmpeg() {
    if (state.loaded && state.ffmpeg) return state.ffmpeg;
    setProgress(null, "Loading the converter (about 30 MB, cached after the first time)...");
    var blob = toBlobURL; // same behavior as @ffmpeg/util toBlobURL (fallback)
    try { blob = (await import(UTIL_ESM)).toBlobURL; } catch (e) { /* use the fallback */ }
    var lib = await import(FFMPEG_DIR + "index.js");
    // Blob URLs for the worker, the core and the wasm: no COOP/COEP headers needed.
    var urls = await Promise.all([
      makeWorkerURL(),
      blob(CORE_JS, "text/javascript"),
      blob(CORE_WASM, "application/wasm")
    ]);
    var ff = new lib.FFmpeg();
    state.logTail = [];
    ff.on("log", function (e) {
      state.logTail.push(e.message);
      if (state.logTail.length > 40) state.logTail.shift();
      var m = /time=(\d+):(\d+):(\d+(?:\.\d+)?)/.exec(e.message);
      if (m && state.expectedSeconds) {
        var t = (+m[1]) * 3600 + (+m[2]) * 60 + parseFloat(m[3]);
        onOutputTime(t);
      }
    });
    await ff.load({ classWorkerURL: urls[0], coreURL: urls[1], wasmURL: urls[2] });
    state.ffmpeg = ff;
    state.loaded = true;
    return ff;
  }

  function onOutputTime(t) {
    var ratio = Math.min(1, t / state.expectedSeconds);
    setProgress(ratio, "Drawing the GIF... " + Math.round(ratio * 100) + "%");
  }

  // ---- file handling ---------------------------------------------------
  function resetResult() {
    show(els.result, false);
    if (state.gifURL) { URL.revokeObjectURL(state.gifURL); state.gifURL = null; }
    els.gif.removeAttribute("src");
  }

  function takeFile(file) {
    clearError();
    resetResult();
    show(els.warn, false);
    show(els.progressBox, false);
    if (!file) return;
    if (file.size > MAX_BYTES) {
      state.file = null;
      show(els.editor, false);
      setText(els.fileNote, "That file is " + fmtBytes(file.size) + ". The limit is 200 MB, because the whole file is held in your browser's memory. Trim it first (for example with the vid2gif command line tool, which has no size limit), then try again.");
      show(els.fileNote, true);
      return;
    }
    state.file = file;
    setText(els.fileNote, file.name + " (" + fmtBytes(file.size) + ")");
    show(els.fileNote, true);
    if (state.videoURL) URL.revokeObjectURL(state.videoURL);
    state.videoURL = URL.createObjectURL(file);
    els.video.src = state.videoURL;
    els.go.disabled = true;
    show(els.editor, true);
    setText(els.videoMeta, "Reading the video...");
  }

  els.video.addEventListener("loadedmetadata", function () {
    var d = els.video.duration, w = els.video.videoWidth, h = els.video.videoHeight;
    setText(els.videoMeta, w + " x " + h + " px, " + (isFinite(d) ? d.toFixed(1) + " s" : "unknown length"));
    els.start.max = isFinite(d) ? Math.max(0, d - 0.5).toFixed(1) : "";
    els.go.disabled = false;
    updateWarn();
  });
  els.video.addEventListener("error", function () {
    setText(els.videoMeta, "Your browser cannot play this file for the preview. You can still try to convert it.");
    els.go.disabled = false;
  });

  function updateWarn() {
    var msgs = [];
    var w = els.video.videoWidth, d = els.video.duration;
    if (state.file && state.file.size > BIG_BYTES) msgs.push("This file is large (" + fmtBytes(state.file.size) + "), so loading it will take a while.");
    if (w >= 3000) msgs.push("4K video is slow in a browser. Lower the length or width if it stalls.");
    if (isFinite(d) && d > 120) msgs.push("Long videos are slow in a browser. Only the part you pick is converted, but the whole file is loaded.");
    if (w && w < +els.width.value) msgs.push("The video is only " + w + " px wide, so the GIF will be " + w + " px wide (it is never scaled up).");
    setText(els.warn, msgs.join(" "));
    show(els.warn, msgs.length > 0);
  }

  els.file.addEventListener("change", function () { takeFile(els.file.files[0]); });
  ["dragenter", "dragover"].forEach(function (n) {
    els.drop.addEventListener(n, function () { els.drop.classList.add("over"); });
  });
  ["dragleave", "drop"].forEach(function (n) {
    els.drop.addEventListener(n, function () { els.drop.classList.remove("over"); });
  });

  els.width.addEventListener("input", function () { setText(els.widthOut, els.width.value); updateWarn(); });
  els.fps.addEventListener("input", function () { setText(els.fpsOut, els.fps.value); });
  els.useTime.addEventListener("click", function () {
    els.start.value = els.video.currentTime.toFixed(1);
  });

  // ---- conversion ------------------------------------------------------
  // Same graph as vid2gif.py build_filter(), with the CLI defaults
  // (256 colors, stats_mode=full, diff_mode=rectangle).
  function buildFilter(width, fps, dither) {
    var use = "paletteuse=dither=" + dither;
    if (dither === "bayer") use += ":bayer_scale=2";
    use += ":diff_mode=rectangle";
    return "[0:v]fps=" + fmtNum(fps) + ",scale=" + width + ":-1:flags=lanczos,split[a][b];" +
           "[a]palettegen=max_colors=256:stats_mode=full[p];[b][p]" + use;
  }

  function readGifInfo(bytes) {
    if (bytes.length < 13) return null;
    var sig = String.fromCharCode.apply(null, bytes.subarray(0, 6));
    if (sig !== "GIF89a" && sig !== "GIF87a") return null;
    return { width: bytes[6] | (bytes[7] << 8), height: bytes[8] | (bytes[9] << 8) };
  }

  function setBusy(on) {
    state.busy = on;
    els.go.disabled = on;
    show(els.cancel, on);
    ["start", "duration", "width", "fps", "dither", "loop", "file", "useTime"].forEach(function (k) { els[k].disabled = on; });
  }

  els.form.addEventListener("submit", async function (ev) {
    ev.preventDefault();
    if (!state.file || state.busy) return;
    clearError();
    resetResult();

    var vw = els.video.videoWidth || 0, vd = els.video.duration;
    var start = Math.max(0, parseFloat(els.start.value) || 0);
    var length = Math.min(MAX_SECONDS, Math.max(0.5, parseFloat(els.duration.value) || 3));
    if (isFinite(vd) && vd > 0) {
      if (start >= vd) { showError("The start time is past the end of the video (" + vd.toFixed(1) + " s)."); return; }
      length = Math.min(length, vd - start);
    }
    els.duration.value = fmtNum(length);
    var width = parseInt(els.width.value, 10);
    if (vw && width > vw) width = vw; // never scale up
    var fps = parseInt(els.fps.value, 10);
    var dither = els.dither.value;
    var loop = els.loop.value;

    setBusy(true);
    state.cancelled = false;
    state.expectedSeconds = length;
    var t0 = performance.now();
    var inName = "input." + ((/\.([a-z0-9]{1,5})$/i.exec(state.file.name) || [0, "mp4"])[1]).toLowerCase();
    var outName = "out.gif";
    var ff = null;
    try {
      ff = await ensureFFmpeg();
      setProgress(null, "Reading your video into memory...");
      var data = new Uint8Array(await state.file.arrayBuffer());
      await ff.writeFile(inName, data);
      data = null;
      setProgress(null, "Reading frames and building the palette, then drawing the GIF...");
      var args = ["-hide_banner", "-y"];
      if (start) args.push("-ss", fmtNum(start));
      args.push("-i", inName, "-t", fmtNum(length), "-an", "-sn", "-dn",
                "-filter_complex", buildFilter(width, fps, dither),
                "-loop", loop, "-f", "gif", outName);
      var code = await ff.exec(args);
      if (state.cancelled) return;
      if (code !== 0) throw new Error("ffmpeg stopped with code " + code + ".\n" + (state.logTail || []).slice(-6).join("\n"));
      var out = await ff.readFile(outName);
      if (!out || !out.length) throw new Error("ffmpeg made an empty file. Try a different start time.");
      var info = readGifInfo(out);
      if (!info) throw new Error("The output was not a valid GIF.");
      var blob = new Blob([out], { type: "image/gif" });
      state.gifURL = URL.createObjectURL(blob);
      els.gif.src = state.gifURL;
      var secs = ((performance.now() - t0) / 1000).toFixed(1);
      setText(els.gifMeta, fmtBytes(blob.size) + " (" + blob.size + " bytes), " + info.width + " x " + info.height + " px, " +
              fmtNum(length) + " s at " + fps + " fps, " + (loop === "0" ? "loops forever" : "plays once") + ". Made in " + secs + " s.");
      els.download.href = state.gifURL;
      els.download.download = state.file.name.replace(/\.[^.]+$/, "") + ".gif";
      show(els.result, true);
      setProgress(1, "Done in " + secs + " s.");
      els.result.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      if (!state.cancelled) {
        var msg = (err && err.message) ? err.message : String(err);
        if (/memory|abort|OOM|RuntimeError/i.test(msg)) msg += "\nThe browser may have run out of memory. Try a smaller file, a shorter length or a smaller width.";
        showError("Could not make the GIF. " + msg);
        show(els.progressBox, false);
        // A crashed wasm instance cannot be reused.
        state.loaded = false; state.ffmpeg = null;
      }
    } finally {
      try { if (ff && state.loaded) { await ff.deleteFile(inName).catch(function () {}); await ff.deleteFile(outName).catch(function () {}); } } catch (e) {}
      setBusy(false);
    }
  });

  els.cancel.addEventListener("click", function () {
    state.cancelled = true;
    try { if (state.ffmpeg) state.ffmpeg.terminate(); } catch (e) {}
    state.ffmpeg = null; state.loaded = false;
    show(els.progressBox, false);
    setText(els.fileNote, "Cancelled. Press Make the GIF to try again.");
    show(els.fileNote, true);
    setBusy(false);
  });
})();
