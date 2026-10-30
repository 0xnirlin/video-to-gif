# vid2gif

Turn a video into a good looking GIF with ffmpeg. One Python file, no dependencies, and an optional target file size.

```
vid2gif clip.mp4
vid2gif clip.mp4 --start 5 --duration 4 --width 640 --fps 20
vid2gif clip.mp4 --max-size 8M
```

If you searched for "video to gif", "ffmpeg gif high quality" or "gif too big", this is the command you were trying to remember.

## What it does

- Builds a palette from your own frames, then uses it to draw the GIF. This is the two-pass palette method, run in one ffmpeg call. It is the single biggest quality win for GIFs.
- Scales with lanczos and keeps the aspect ratio. It never scales up past the source.
- Lets you pick the dither, the number of colors, the frame rate and the loop count.
- With `--max-size` it tries settings from best to smallest until the GIF fits, and tells you what it chose.
- Prints the final size, dimensions, frame count and duration.
- Runs on your machine. Nothing is uploaded.

## Install

You need Python 3.8 or newer and ffmpeg (with ffprobe) on your PATH.

```
# ffmpeg
brew install ffmpeg            # macOS
sudo apt install ffmpeg        # Debian, Ubuntu
winget install ffmpeg          # Windows

# vid2gif
pipx install git+https://github.com/0xnirlin/video-to-gif
```

Or skip the install. The tool is the single file `vid2gif.py`. Clone the repo and run it directly:

```
git clone https://github.com/0xnirlin/video-to-gif
cd video-to-gif
./vid2gif in.mp4
python3 vid2gif in.mp4
```

## Examples

```
# Whole video, default settings (480 px wide, 15 fps, loops forever)
vid2gif in.mp4

# 4 seconds starting at 0:05, wider and smoother
vid2gif in.mp4 --start 5 --duration 4 --width 640 --fps 20

# From 1:10 to 1:14, written to a chosen file
vid2gif in.mp4 --start 1:10 --end 1:14 -o reaction.gif

# Play once and stop
vid2gif in.mp4 --once

# Fewer colors, smaller file
vid2gif in.mp4 --colors 64

# Fit under 8 MB
vid2gif in.mp4 --max-size 8M

# Fit under 500 KB, replacing an old file
vid2gif in.mp4 --max-size 500K -o small.gif --overwrite
```

Example output with `--max-size`:

```
try  1/12 as requested   480 px    15 fps  256 colors  ->  1000.8 KB  too big
try  2/12 fps 12         480 px    12 fps  256 colors  ->  811.8 KB  too big
try  3/12 fps 10         480 px    10 fps  256 colors  ->  675.4 KB  too big
try  4/12 fps 8          480 px     8 fps  256 colors  ->  546.2 KB  too big
try  5/12 width 408      408 px     8 fps  256 colors  ->  404.0 KB  fits
chose: 408 px wide, 8 fps, 256 colors (reduced to width 408)
wrote gradients.gif
  size:       404.0 KB (413691 bytes)
  dimensions: 408 x 230
  frames:     24
  duration:   3.01 s, loops forever
```

### All options

| Option | Meaning |
| --- | --- |
| `-o, --output FILE` | Output file. Default is the input name with `.gif`. |
| `--overwrite` | Replace the output file if it exists. |
| `--start TIME` | Start time, in seconds or `mm:ss`. Default 0. |
| `--duration SECONDS` | Length of the clip. Default is until the end. |
| `--end TIME` | End time, instead of `--duration`. |
| `--width PX` | Output width. Height follows. Default 480, never above the source. |
| `--fps N` | Frames per second. Default 15. |
| `--loop N` | Extra repeats. 0 means forever, which is the default. |
| `--once` | Play once and stop. |
| `--dither` | `sierra2_4a` (default), `bayer`, `floyd_steinberg` or `none`. |
| `--bayer-scale 0-5` | Pattern size, only with `--dither bayer`. Default 2. |
| `--colors N` | Maximum palette size, 2 to 256. Default 256. |
| `--stats-mode` | `full` (default) or `diff`. Diff builds the palette from the moving parts. |
| `--max-size SIZE` | Target size such as `8M` or `500K`. Sizes use 1024 per K. |

Exit codes: 0 on success, 1 for an error (missing file, no ffmpeg, ffmpeg failed), 2 for bad options, 3 when `--max-size` cannot be met. When nothing fits, no file is written and the message tells you the smallest size it reached.

## Why GIFs look bad

A GIF can hold only 256 colors per frame. A video frame can hold millions. Something has to give.

1. **256 colors.** Every pixel must be one of 256 colors. Smooth areas such as skies, skin and gradients turn into visible bands.
2. **A generic palette.** By default ffmpeg uses a fixed palette that was not built for your video. Most of its colors are wasted on shades your clip never uses, so reds, blues and skin tones look washed out.
3. **Dithering.** To fake the colors it cannot show, a GIF mixes dots of nearby colors. Good dithering hides banding. Bad or no dithering leaves hard steps. Too much leaves noise.

vid2gif fixes the second problem for you. It first scans the frames and picks the 256 colors that this clip needs, then draws every frame with that palette. You can then tune the dither and color count for the third.

## Real sizes

These numbers are measured, not estimated. Two synthetic 3 second clips, 640x360 at 24 fps, made with ffmpeg 8.0.1:

```
ffmpeg -f lavfi -i "testsrc2=size=640x360:rate=24:duration=3" -pix_fmt yuv420p -c:v libx264 -crf 20 testsrc.mp4
ffmpeg -f lavfi -i "gradients=size=640x360:rate=24:duration=3:speed=0.02" -pix_fmt yuv420p -c:v libx264 -crf 18 gradients.mp4
```

`testsrc2` is a busy test pattern with sharp text and many colors. `gradients` is a slow, smooth color blend, the hard case for GIF. Sizes are in KB (1024 bytes). **SSIM** compares each GIF with the source at the same size and frame rate: 1.000 is identical, lower is worse.

| Command | testsrc2 size | SSIM | gradients size | SSIM |
| --- | --- | --- | --- | --- |
| `ffmpeg -i in.mp4 out.gif` (naive, 640 px, 24 fps) | 1030.8 KB | 0.812 | 658.1 KB | 0.150 |
| naive ffmpeg, scaled to 480 px, 15 fps | 482.4 KB | 0.776 | 294.9 KB | 0.152 |
| `vid2gif in.mp4` (480 px, 15 fps) | 767.4 KB | 0.934 | 1000.8 KB | 0.997 |
| `vid2gif in.mp4 --dither none` | 659.5 KB | 0.936 | 974.0 KB | 0.997 |
| `vid2gif in.mp4 --dither bayer --bayer-scale 3` | 734.2 KB | 0.613 | 1153.7 KB | 0.968 |
| `vid2gif in.mp4 --stats-mode diff` | 712.7 KB | 0.842 | 1014.8 KB | 0.997 |
| `vid2gif in.mp4 --colors 128` | 670.5 KB | 0.922 | 869.4 KB | 0.996 |
| `vid2gif in.mp4 --width 320 --fps 12` | 304.7 KB | 0.881 | 396.8 KB | 0.997 |
| `vid2gif in.mp4 --max-size 500K` | 430.3 KB (480 px, 8 fps) | 0.965 | 404.0 KB (408 px, 8 fps) | 0.999 |

What to read from this:

- The naive GIF is small because it throws quality away. On the smooth clip its SSIM is 0.15, and you can see it: the colors wash out and a dot pattern covers the picture. vid2gif at the same dimensions is bigger but looks like the source.
- On the smooth clip, vid2gif at 480 px is about 3.4 times the size of the naive 480 px GIF. That is the price of keeping the gradient clean. Use `--max-size`, `--width` or `--fps` to get it back down. For that clip, `--max-size 500K` landed at 404 KB with an SSIM of 0.999.
- Width and frame rate are the big size levers. Colors are a small lever on these clips.
- Dither choice matters. The default `sierra2_4a` is a safe pick. `bayer` adds a cross-hatch pattern and scored worst here, so try it only if you like that look.
- Your footage will behave differently. Real video with lots of motion makes bigger GIFs than these clips. Treat the table as a guide, and run your own clip with `--max-size`.

## Gif too big?

GIF is an old format and it gets big fast. File size grows with width, frame rate, length and colors. To shrink a GIF:

1. Cut the clip shorter with `--start` and `--duration`.
2. Lower the width, for example `--width 360`.
3. Lower the frame rate, for example `--fps 10`.
4. Let the tool do it: `vid2gif in.mp4 --max-size 8M`.

Every site and app has its own upload limit, and the limits change. Look up the number on your platform's own help page, then pass it to `--max-size`.

## FAQ

**Does it keep the sound?**
No. GIFs have no audio.

**Why is my GIF bigger than the original video?**
GIF compresses far worse than MP4 or WebM. A short clip as a GIF can be many times larger than the video. If the site you post to accepts MP4 or WebM, those are better. Use GIF when you need it.

**What is the difference between `sierra2_4a`, `floyd_steinberg` and `none`?**
They are ways of spreading the color error between neighbouring pixels. `sierra2_4a` is the default and works well for most video. `floyd_steinberg` is the classic error diffusion method. `none` leaves flat colors, which can be best for screen recordings and logos.

**What does `--stats-mode diff` do?**
It builds the palette from the parts of the picture that move. This can help when a small moving subject sits on a still background. For full-frame video the default is usually better.

**Can I make it loop a fixed number of times?**
Yes, `--loop 3` repeats three extra times. `--once` plays once. The default is forever.

**Will it upscale my video?**
No. It never goes above the source width or the source frame rate.

**It says ffmpeg is not found.**
Install ffmpeg (see Install) and open a new terminal so the PATH updates. Check with `ffmpeg -version` and `ffprobe -version`.

**Which Python?**
3.8 or newer. There are no third-party packages.

## No terminal?

If you do not want to install anything, there is [a free browser version](https://getziztu.com/tools/video-to-gif?utm_source=github&utm_medium=readme&utm_campaign=video-to-gif). It is free, needs no account, takes files up to 100 MB and makes GIFs of 1 to 15 seconds.

## Development

```
python3 -m unittest discover -s tests -v
```

The tests build small clips with ffmpeg and check the width, the loop flag, the frame count and that `--max-size` really fits. They need ffmpeg on your PATH.

## License

MIT. Copyright (c) 2026 Ziztu.
