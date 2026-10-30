"""Video to GIF (high quality). Gradio front end for vid2gif.

The conversion logic is vid2gif.py, copied next to this file so the Space is
self-contained. It calls ffmpeg (installed through packages.txt).
"""

import os
import tempfile

import vid2gif

try:
    import gradio as gr
except ImportError:  # lets the conversion function be tested without Gradio
    gr = None

MAX_UPLOAD_MB = 50
MAX_SECONDS = 15
GITHUB_URL = "https://github.com/0xnirlin/video-to-gif"
ZIZTU_URL = ("https://getziztu.com/tools/video-to-gif"
             "?utm_source=huggingface&utm_medium=space&utm_campaign=video-to-gif")


def _error(message):
    return gr.Error(message) if gr else ValueError(message)


def convert_video(video, start, duration, width, fps, loop, max_size_mb):
    """Convert an uploaded video. Returns (gif_path, summary_text)."""
    if not video:
        raise _error("Upload a video first.")
    if os.path.getsize(video) > MAX_UPLOAD_MB * 1024 * 1024:
        raise _error("That file is over %d MB. Trim it or compress it first." % MAX_UPLOAD_MB)

    duration = max(0.5, min(float(duration), MAX_SECONDS))
    settings = {"width": int(width), "fps": float(fps), "colors": 256,
                "dither": "sierra2_4a", "bayer_scale": 2, "stats_mode": "full"}
    max_bytes = int(float(max_size_mb) * 1024 * 1024) if max_size_mb and float(max_size_mb) > 0 else None
    out = os.path.join(tempfile.mkdtemp(prefix="vid2gif-"), "output.gif")
    try:
        chosen, label, info = vid2gif.convert(
            video, out, settings, float(start), duration,
            0 if loop else -1, max_bytes, True, say=lambda *a, **k: None)
    except vid2gif.Vid2GifError as exc:
        raise _error(str(exc))

    size = os.path.getsize(out)
    lines = ["**%s**, %d x %d, %d frames, %.1f s, %s" % (
        vid2gif.human_size(size), info["width"], info["height"], info["frames"],
        info["duration"], "loops forever" if loop else "plays once")]
    if max_bytes and label and label != "as requested":
        lines.append("To fit your size limit it used %d px wide, %s fps, %d colors."
                     % (chosen["width"], vid2gif.fmt_num(chosen["fps"]), chosen["colors"]))
    return out, "\n\n".join(lines)


def build_demo():
    with gr.Blocks(title="Video to GIF (high quality)") as demo:
        gr.Markdown(
            "# Video to GIF (high quality)\n"
            "Builds a palette from your own frames, so colors stay clean. "
            "Upload up to %d MB, make a GIF of up to %d seconds. Nothing is kept."
            % (MAX_UPLOAD_MB, MAX_SECONDS))
        with gr.Row():
            with gr.Column():
                video = gr.Video(label="Video", sources=["upload"])
                start = gr.Slider(0, 600, value=0, step=0.5, label="Start (seconds)")
                duration = gr.Slider(1, MAX_SECONDS, value=5, step=0.5,
                                     label="Duration (seconds, max %d)" % MAX_SECONDS)
                width = gr.Slider(240, 720, value=480, step=2, label="Width (pixels)")
                fps = gr.Slider(8, 24, value=15, step=1, label="Frames per second")
                loop = gr.Checkbox(value=True, label="Loop forever")
                max_size = gr.Number(value=0, minimum=0, maximum=MAX_UPLOAD_MB,
                                     label="Max size in MB (0 = no limit)")
                run = gr.Button("Make GIF", variant="primary")
            with gr.Column():
                result = gr.Image(label="GIF", type="filepath", interactive=False)
                summary = gr.Markdown()
        run.click(convert_video,
                  inputs=[video, start, duration, width, fps, loop, max_size],
                  outputs=[result, summary])
        gr.Markdown(
            "Open source: [%s](%s). No terminal? "
            "[A free browser version](%s) is also available."
            % ("0xnirlin/video-to-gif", GITHUB_URL, ZIZTU_URL))
    return demo


if gr is not None:
    demo = build_demo()
    if __name__ == "__main__":
        demo.queue(max_size=8).launch(max_file_size="%dmb" % MAX_UPLOAD_MB)
