#!/usr/bin/env python3
"""vid2gif: turn a video into a good looking GIF with ffmpeg.

Uses the two-pass palette method (palettegen + paletteuse) in one ffmpeg call,
so every GIF gets a palette built from its own frames. Standard library only.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

__version__ = "1.0.0"

DITHERS = ("sierra2_4a", "bayer", "floyd_steinberg", "none")
STATS_MODES = ("full", "diff")
DEFAULT_WIDTH = 480
DEFAULT_FPS = 15
MIN_WIDTH = 96


class Vid2GifError(Exception):
    """A problem the user can act on. Printed without a traceback."""


# ----------------------------------------------------------------------------
# Parsing helpers
# ----------------------------------------------------------------------------

def parse_size(text):
    """'8M', '500K', '1.5MB', '2000000' -> bytes (KB and MB are 1024-based)."""
    m = re.fullmatch(r"\s*([0-9]*\.?[0-9]+)\s*([kKmMgG]?)[bB]?\s*", str(text))
    if not m:
        raise argparse.ArgumentTypeError(
            "bad size %r, use something like 8M, 500K or 2000000" % text)
    value = float(m.group(1))
    mult = {"": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}[m.group(2).lower()]
    size = int(value * mult)
    if size <= 0:
        raise argparse.ArgumentTypeError("size must be above zero")
    return size


def parse_time(text):
    """'12', '12.5', '1:05', '0:01:05.5' -> seconds (float)."""
    s = str(text).strip()
    try:
        if ":" in s:
            parts = s.split(":")
            if len(parts) > 3:
                raise ValueError
            total = 0.0
            for p in parts:
                total = total * 60 + float(p)
        else:
            total = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "bad time %r, use seconds (12.5) or mm:ss (1:05)" % text)
    if total < 0:
        raise argparse.ArgumentTypeError("time cannot be negative")
    return total


def human_size(n):
    if n >= 1024 ** 2:
        return "%.2f MB" % (n / 1024 ** 2)
    if n >= 1024:
        return "%.1f KB" % (n / 1024)
    return "%d B" % n


def _int_range(lo, hi, name):
    def conv(text):
        try:
            v = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError("%s must be a whole number" % name)
        if not lo <= v <= hi:
            raise argparse.ArgumentTypeError(
                "%s must be between %d and %d" % (name, lo, hi))
        return v
    return conv


def _positive_float(name):
    def conv(text):
        try:
            v = float(text)
        except ValueError:
            raise argparse.ArgumentTypeError("%s must be a number" % name)
        if v <= 0:
            raise argparse.ArgumentTypeError("%s must be above zero" % name)
        return v
    return conv


# ----------------------------------------------------------------------------
# ffmpeg / ffprobe
# ----------------------------------------------------------------------------

def find_tools():
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        missing = " and ".join(n for n, p in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not p)
        raise Vid2GifError(
            "%s not found on your PATH. Install ffmpeg first:\n"
            "  macOS:          brew install ffmpeg\n"
            "  Debian/Ubuntu:  sudo apt install ffmpeg\n"
            "  Windows:        winget install ffmpeg" % missing)
    return ffmpeg, ffprobe


def probe(ffprobe, path):
    """Return dict(width, height, duration, fps) for the first video stream."""
    cmd = [ffprobe, "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=width,height,avg_frame_rate,r_frame_rate,duration:format=duration:stream_side_data=rotation",
           "-of", "default=noprint_wrappers=1", path]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
    except OSError as exc:
        raise Vid2GifError("could not run ffprobe: %s" % exc)
    info = {}
    for line in res.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            info.setdefault(k.strip(), v.strip())
    if res.returncode != 0 or "width" not in info:
        detail = res.stderr.strip().splitlines()
        hint = (": " + detail[-1]) if detail else ""
        raise Vid2GifError("%s has no readable video stream%s" % (path, hint))
    try:
        width, height = int(info["width"]), int(info["height"])
    except ValueError:
        raise Vid2GifError("%s has no readable video stream" % path)
    rotation = 0
    try:
        rotation = abs(int(float(info.get("rotation", "0"))))
    except ValueError:
        pass
    if rotation % 180 == 90:
        width, height = height, width

    def num(key):
        v = info.get(key)
        try:
            return float(v) if v not in (None, "N/A", "") else None
        except ValueError:
            return None

    def rate(key):
        v = info.get(key, "")
        try:
            if "/" in v:
                a, b = v.split("/")
                return float(a) / float(b) if float(b) else None
            return float(v) if v else None
        except ValueError:
            return None

    duration = num("duration")
    if duration is None:
        # the stream line came first; the format line is a second "duration"
        # key that setdefault ignored, so ask for it directly
        duration = _format_duration(ffprobe, path)
    fps = rate("avg_frame_rate") or rate("r_frame_rate")
    return {"width": width, "height": height, "duration": duration, "fps": fps}


def _format_duration(ffprobe, path):
    cmd = [ffprobe, "-v", "error", "-show_entries", "format=duration",
           "-of", "default=noprint_wrappers=1:nokey=1", path]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         universal_newlines=True)
    try:
        return float(res.stdout.strip())
    except ValueError:
        return None


def build_filter(width, fps, colors, dither, bayer_scale, stats_mode):
    pal = "palettegen=max_colors=%d:stats_mode=%s" % (colors, stats_mode)
    use = "paletteuse=dither=%s" % dither
    if dither == "bayer":
        use += ":bayer_scale=%d" % bayer_scale
    use += ":diff_mode=rectangle"
    return ("[0:v]fps=%s,scale=%d:-1:flags=lanczos,split[a][b];"
            "[a]%s[p];[b][p]%s" % (fmt_num(fps), width, pal, use))


def fmt_num(x):
    return ("%g" % x)


def run_ffmpeg(ffmpeg, src, out, start, length, settings, loop):
    """One ffmpeg call. Writes to `out` (a temp path), raises on failure."""
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-nostdin"]
    if start:
        cmd += ["-ss", fmt_num(start)]
    cmd += ["-i", src]
    if length is not None:
        cmd += ["-t", fmt_num(length)]
    cmd += ["-an", "-sn", "-dn", "-filter_complex",
            build_filter(settings["width"], settings["fps"], settings["colors"],
                         settings["dither"], settings["bayer_scale"],
                         settings["stats_mode"]),
            "-loop", str(loop), "-f", "gif", out]
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
    except OSError as exc:
        raise Vid2GifError("could not run ffmpeg: %s" % exc)
    if res.returncode != 0:
        lines = [l for l in res.stderr.strip().splitlines() if l.strip()]
        tail = "\n  ".join(lines[-6:]) if lines else "(no message)"
        raise Vid2GifError("ffmpeg failed:\n  " + tail)
    if not os.path.exists(out) or os.path.getsize(out) == 0:
        raise Vid2GifError(
            "ffmpeg produced no frames. Is --start past the end of the video?")


# ----------------------------------------------------------------------------
# GIF reader (pure Python, so the summary needs no extra ffprobe call)
# ----------------------------------------------------------------------------

def gif_info(path):
    """Parse a GIF. Returns dict(width, height, frames, duration, loop).

    loop is None when there is no NETSCAPE loop block (plays once), 0 for
    forever, or N for N extra plays.
    """
    with open(path, "rb") as fh:
        data = fh.read()
    if data[:6] not in (b"GIF87a", b"GIF89a"):
        raise Vid2GifError("%s is not a GIF" % path)
    width = data[6] | (data[7] << 8)
    height = data[8] | (data[9] << 8)
    flags = data[10]
    pos = 13
    if flags & 0x80:
        pos += 3 * (2 ** ((flags & 7) + 1))
    frames = 0
    delay_cs = 0
    loop = None
    n = len(data)

    def skip_sub_blocks(p):
        while p < n:
            size = data[p]
            p += 1
            if size == 0:
                return p
            p += size
        return p

    while pos < n:
        b = data[pos]
        if b == 0x3B:
            break
        if b == 0x21:
            label = data[pos + 1]
            if label == 0xF9 and data[pos + 2] >= 4:
                delay_cs += data[pos + 4] | (data[pos + 5] << 8)
            elif label == 0xFF and data[pos + 2] == 11 \
                    and data[pos + 3:pos + 14] in (b"NETSCAPE2.0", b"ANIMEXTS1.0") \
                    and data[pos + 14] >= 3 and data[pos + 15] == 1:
                loop = data[pos + 16] | (data[pos + 17] << 8)
            pos = skip_sub_blocks(pos + 2)
        elif b == 0x2C:
            frames += 1
            lflags = data[pos + 9]
            pos += 10
            if lflags & 0x80:
                pos += 3 * (2 ** ((lflags & 7) + 1))
            pos += 1  # LZW minimum code size
            pos = skip_sub_blocks(pos)
        else:
            break
    return {"width": width, "height": height, "frames": frames,
            "duration": delay_cs / 100.0, "loop": loop}


# ----------------------------------------------------------------------------
# Conversion with optional size target
# ----------------------------------------------------------------------------

def even(x):
    return max(2, int(round(x / 2.0)) * 2)


def size_ladder(settings):
    """Yield (label, settings) from best quality to smallest.

    Order: lower fps first, then smaller width, then fewer colors.
    """
    steps = []
    cur = dict(settings)
    steps.append(("as requested", dict(cur)))

    fps_options = []
    for f in (15, 12, 10, 8):
        if f < settings["fps"]:
            fps_options.append(f)
    for f in fps_options:
        cur = dict(cur, fps=f)
        steps.append(("fps %s" % fmt_num(f), dict(cur)))

    base_w = settings["width"]
    seen = {base_w}
    for factor in (0.85, 0.7, 0.55, 0.4, 0.3):
        w = even(base_w * factor)
        if w < MIN_WIDTH or w in seen:
            continue
        seen.add(w)
        cur = dict(cur, width=w)
        steps.append(("width %d" % w, dict(cur)))

    for c in (128, 64, 32):
        if c < settings["colors"]:
            cur = dict(cur, colors=c)
            steps.append(("%d colors" % c, dict(cur)))
    return steps


def convert(src, out, settings, start, length, loop, max_size, overwrite,
            say=print):
    ffmpeg, ffprobe = find_tools()
    if not os.path.isfile(src):
        raise Vid2GifError("input file not found: %s" % src)
    out_dir = os.path.dirname(os.path.abspath(out))
    if not os.path.isdir(out_dir):
        raise Vid2GifError("output folder does not exist: %s" % out_dir)
    if os.path.exists(out) and not overwrite:
        raise Vid2GifError("%s already exists. Use --overwrite to replace it." % out)
    if os.path.abspath(out) == os.path.abspath(src):
        raise Vid2GifError("output would overwrite the input file")

    meta = probe(ffprobe, src)
    total = meta["duration"]
    if total is not None and start >= total:
        raise Vid2GifError(
            "--start %s is past the end of the video (%.2f s long)" % (fmt_num(start), total))
    if length is None and total is not None:
        length = total - start
    elif length is not None and total is not None:
        length = min(length, total - start)
    if length is not None and length <= 0:
        raise Vid2GifError("nothing to convert: the clip length is zero")

    settings = dict(settings)
    if settings["width"] > meta["width"]:
        say("note: source is only %d px wide, using that instead of %d" %
            (meta["width"], settings["width"]))
        settings["width"] = meta["width"]
    if meta["fps"] and settings["fps"] > meta["fps"] + 0.01:
        settings["fps"] = meta["fps"]
        say("note: source is %s fps, using that" % fmt_num(round(meta["fps"], 3)))

    tmp = os.path.join(out_dir, ".%s.part" % os.path.basename(out))
    try:
        if max_size is None:
            run_ffmpeg(ffmpeg, src, tmp, start, length, settings, loop)
            chosen, label = settings, None
        else:
            chosen, label, smallest = None, None, None
            ladder = size_ladder(settings)
            for i, (lab, trial) in enumerate(ladder, 1):
                run_ffmpeg(ffmpeg, src, tmp, start, length, trial, loop)
                size = os.path.getsize(tmp)
                smallest = size if smallest is None else min(smallest, size)
                fits = size <= max_size
                say("try %2d/%-2d %-13s %4s px  %4s fps  %3d colors  ->  %s  %s" % (
                    i, len(ladder), lab, trial["width"], fmt_num(trial["fps"]),
                    trial["colors"], human_size(size), "fits" if fits else "too big"))
                if fits:
                    chosen, label = trial, lab
                    break
            if chosen is None:
                raise SizeTargetError(
                    "could not fit %s. The smallest try was %s (%d px wide, %s fps, %d colors). "
                    "Use a shorter --duration or a larger --max-size." % (
                        human_size(max_size), human_size(smallest),
                        trial["width"], fmt_num(trial["fps"]), trial["colors"]))
        os.replace(tmp, out)
    except KeyboardInterrupt:
        _cleanup(tmp)
        raise
    except Exception:
        _cleanup(tmp)
        raise
    return chosen, label, gif_info(out)


class SizeTargetError(Vid2GifError):
    pass


def _cleanup(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(
        prog="vid2gif",
        description="Turn a video into a high quality GIF with ffmpeg "
                    "(two-pass palette method).",
        epilog="examples:\n"
               "  vid2gif clip.mp4\n"
               "  vid2gif clip.mp4 --start 5 --duration 4 --width 640 --fps 20\n"
               "  vid2gif clip.mp4 --max-size 8M -o small.gif",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("input", help="input video file (anything ffmpeg can read)")
    p.add_argument("-o", "--output", help="output file (default: input name with .gif)")
    p.add_argument("--overwrite", action="store_true", help="replace the output file if it exists")
    p.add_argument("--start", type=parse_time, default=0.0, metavar="TIME",
                   help="start time, seconds or mm:ss (default 0)")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--duration", type=_positive_float("duration"), metavar="SECONDS",
                   help="length of the clip (default: until the end)")
    g.add_argument("--end", type=parse_time, metavar="TIME",
                   help="end time, seconds or mm:ss (instead of --duration)")
    p.add_argument("--width", type=_int_range(16, 7680, "width"), default=DEFAULT_WIDTH,
                   help="output width in pixels, height follows (default %d, never above the source)" % DEFAULT_WIDTH)
    p.add_argument("--fps", type=_positive_float("fps"), default=DEFAULT_FPS,
                   help="frames per second (default %d)" % DEFAULT_FPS)
    lg = p.add_mutually_exclusive_group()
    lg.add_argument("--loop", type=_int_range(0, 65535, "loop"), default=0, metavar="N",
                    help="how many extra times to repeat, 0 = forever (default)")
    lg.add_argument("--once", action="store_true", help="play once and stop")
    p.add_argument("--dither", choices=DITHERS, default="sierra2_4a",
                   help="dither method (default sierra2_4a)")
    p.add_argument("--bayer-scale", type=_int_range(0, 5, "bayer scale"), default=2, metavar="0-5",
                   help="bayer pattern size, only with --dither bayer (default 2)")
    p.add_argument("--colors", type=_int_range(2, 256, "colors"), default=256,
                   help="maximum palette size, 2 to 256 (default 256)")
    p.add_argument("--stats-mode", choices=STATS_MODES, default="full",
                   help="palette stats: full = whole frame, diff = moving parts (default full)")
    p.add_argument("--max-size", type=parse_size, metavar="SIZE",
                   help="target file size like 8M or 500K. Tries lower fps, then smaller "
                        "width, then fewer colors until it fits")
    p.add_argument("--version", action="version", version="vid2gif " + __version__)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)

    out = args.output
    if not out:
        base, _ = os.path.splitext(args.input)
        out = base + ".gif"

    length = args.duration
    if args.end is not None:
        if args.end <= args.start:
            print("vid2gif: error: --end must be after --start", file=sys.stderr)
            return 2
        length = args.end - args.start

    loop = -1 if args.once else args.loop
    settings = {"width": args.width, "fps": args.fps, "colors": args.colors,
                "dither": args.dither, "bayer_scale": args.bayer_scale,
                "stats_mode": args.stats_mode}
    if args.bayer_scale != 2 and args.dither != "bayer":
        print("note: --bayer-scale only applies with --dither bayer")

    try:
        chosen, label, info = convert(args.input, out, settings, args.start, length,
                                      loop, args.max_size, args.overwrite)
    except SizeTargetError as exc:
        print("vid2gif: error: %s" % exc, file=sys.stderr)
        return 3
    except Vid2GifError as exc:
        print("vid2gif: error: %s" % exc, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nvid2gif: cancelled", file=sys.stderr)
        return 130

    size = os.path.getsize(out)
    if args.max_size is not None:
        print("chose: %s px wide, %s fps, %d colors (%s)" % (
            chosen["width"], fmt_num(chosen["fps"]), chosen["colors"],
            "first try fit" if label == "as requested" else "reduced to " + label))
    loop_text = "plays once" if info["loop"] is None else (
        "loops forever" if info["loop"] == 0 else "repeats %d times" % info["loop"])
    print("wrote %s" % out)
    print("  size:       %s (%d bytes)" % (human_size(size), size))
    print("  dimensions: %d x %d" % (info["width"], info["height"]))
    print("  frames:     %d" % info["frames"])
    print("  duration:   %.2f s, %s" % (info["duration"], loop_text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
