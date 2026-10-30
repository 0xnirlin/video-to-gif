---
title: Video to GIF (high quality)
emoji: 🎞️
colorFrom: indigo
colorTo: pink
sdk: static
app_file: index.html
pinned: false
license: mit
short_description: Browser-only video to GIF with a clean palette
---

# Video to GIF (high quality), in your browser

Pick a video and get a clean GIF. Everything runs inside the page with ffmpeg.wasm, so your video never leaves your device.

- Choose a video up to 200 MB and preview it.
- Set the start, the length (up to 15 seconds), the width (240 to 720 px) and the frame rate (8 to 24).
- Pick the dither and loop forever or play once.
- The page shows the GIF, its size in KB or MB and its dimensions, and gives you a download button.

## How the GIF is made

It uses the same ffmpeg filter graph as the command line tool vid2gif, the two-pass palette method:

```
[0:v]fps=15,scale=480:-1:flags=lanczos,split[a][b];
[a]palettegen=max_colors=256:stats_mode=full[p];
[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle
```

The page scans your frames, picks the 256 colors your clip needs, then draws every frame with that palette. The width is never scaled up past the source.

## Limits

- Files over 200 MB are refused, because the whole file is held in browser memory.
- Very long or 4K clips can be slow in a browser, and a phone may run out of memory.
- The converter (about 30 MB) is downloaded from the jsDelivr CDN the first time you convert, so the page needs a network connection.

## How it works under the hood

The page loads these packages from cdn.jsdelivr.net, pinned to exact versions:

- `@ffmpeg/ffmpeg` 0.12.15
- `@ffmpeg/util` 0.12.2
- `@ffmpeg/core` 0.12.10 (the single-thread build)

The core, the wasm file and the worker are loaded as blob URLs. The single-thread core needs no cross-origin isolation headers, so it works on a static Space.

## Links

- Command line tool and source: [github.com/0xnirlin/video-to-gif](https://github.com/0xnirlin/video-to-gif)
- More free video tools: [Ziztu](https://getziztu.com/tools/video-to-gif?utm_source=huggingface&utm_medium=space&utm_campaign=video-to-gif)

MIT licensed. Copyright (c) 2026 Ziztu.
