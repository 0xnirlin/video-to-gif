---
title: Video to GIF (high quality)
emoji: 🎞️
colorFrom: indigo
colorTo: pink
sdk: gradio
sdk_version: 6.30.0
app_file: app.py
pinned: false
license: mit
short_description: Clean, small GIFs from any video, with a size target
---

# Video to GIF (high quality)

Upload a video and get a clean GIF. The tool builds a palette from your own frames (the two-pass palette method), so colors stay clear instead of washed out.

- Upload up to 50 MB.
- Pick the start, the length (up to 15 seconds), the width (240 to 720 px) and the frame rate (8 to 24).
- Loop forever or play once.
- Optional max size in MB. The tool lowers the frame rate, then the width, then the colors until the GIF fits.

The same code is a command line tool: [github.com/0xnirlin/video-to-gif](https://github.com/0xnirlin/video-to-gif). It runs on your own machine with ffmpeg and has more options.

No terminal? There is also [a free browser version](https://getziztu.com/tools/video-to-gif?utm_source=huggingface&utm_medium=space&utm_campaign=video-to-gif).

MIT licensed. Copyright (c) 2026 Ziztu.
