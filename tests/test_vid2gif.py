"""Tests for vid2gif. Needs ffmpeg and ffprobe on PATH.

Run from the repo root:  python3 -m unittest discover -s tests -v
"""

import argparse
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import vid2gif  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_clip(path, source, seconds=2, size="320x180", rate=24):
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
           "-i", "%s=size=%s:rate=%d:duration=%s" % (source, size, rate, seconds),
           "-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "18", path]
    subprocess.run(cmd, check=True)


def run_cli(*args):
    """Run main() in-process, return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = vid2gif.main(list(args))
        except SystemExit as exc:  # argparse errors
            code = exc.code
    return code, out.getvalue(), err.getvalue()


class ParseTests(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(vid2gif.parse_size("500K"), 500 * 1024)
        self.assertEqual(vid2gif.parse_size("8M"), 8 * 1024 * 1024)
        self.assertEqual(vid2gif.parse_size("1.5MB"), int(1.5 * 1024 * 1024))
        self.assertEqual(vid2gif.parse_size("2000"), 2000)

    def test_bad_size(self):
        for bad in ("big", "", "-3M", "0"):
            with self.assertRaises(argparse.ArgumentTypeError):
                vid2gif.parse_size(bad)

    def test_times(self):
        self.assertEqual(vid2gif.parse_time("12.5"), 12.5)
        self.assertEqual(vid2gif.parse_time("1:05"), 65)
        self.assertEqual(vid2gif.parse_time("1:01:05.5"), 3665.5)

    def test_filter_has_two_pass_palette(self):
        f = vid2gif.build_filter(320, 15, 256, "sierra2_4a", 2, "full")
        self.assertIn("split", f)
        self.assertIn("palettegen=max_colors=256:stats_mode=full", f)
        self.assertIn("paletteuse=dither=sierra2_4a", f)
        self.assertIn("lanczos", f)
        self.assertNotIn("bayer_scale", f)
        self.assertIn("bayer_scale=4",
                      vid2gif.build_filter(320, 15, 256, "bayer", 4, "full"))

    def test_ladder_order(self):
        base = {"width": 480, "fps": 15, "colors": 256, "dither": "sierra2_4a",
                "bayer_scale": 2, "stats_mode": "full"}
        steps = [s for _, s in vid2gif.size_ladder(base)]
        self.assertEqual(steps[0], base)
        # fps drops first, then width, then colors, never the other way round
        fps = [s["fps"] for s in steps]
        widths = [s["width"] for s in steps]
        colors = [s["colors"] for s in steps]
        self.assertEqual(fps, sorted(fps, reverse=True))
        self.assertEqual(widths, sorted(widths, reverse=True))
        self.assertEqual(colors, sorted(colors, reverse=True))
        first_width_drop = next(i for i, w in enumerate(widths) if w < 480)
        first_color_drop = next(i for i, c in enumerate(colors) if c < 256)
        self.assertEqual(min(fps[first_width_drop:]), fps[first_width_drop])
        self.assertLess(first_width_drop, first_color_drop)


@unittest.skipUnless(HAVE_FFMPEG, "ffmpeg not installed")
class ConvertTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="vid2gif-test-")
        cls.testsrc = os.path.join(cls.tmp, "testsrc.mp4")
        cls.gradient = os.path.join(cls.tmp, "gradient.mp4")
        make_clip(cls.testsrc, "testsrc2")
        make_clip(cls.gradient, "gradients", rate=24)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def out(self, name):
        return os.path.join(self.tmp, name)

    def test_basic_gif(self):
        out = self.out("basic.gif")
        code, stdout, _ = run_cli(self.testsrc, "-o", out, "--overwrite")
        self.assertEqual(code, 0)
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(6), b"GIF89a")
        info = vid2gif.gif_info(out)
        self.assertEqual(info["width"], 320)  # source is 320, default 480 is capped
        self.assertEqual(info["height"], 180)
        self.assertEqual(info["loop"], 0)  # forever by default
        self.assertAlmostEqual(info["duration"], 2.0, delta=0.15)
        self.assertIn("size:", stdout)
        self.assertIn("frames:", stdout)

    def test_default_output_name(self):
        src = self.out("named.mp4")
        shutil.copy(self.testsrc, src)
        code, _, _ = run_cli(src, "--duration", "1")
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(self.out("named.gif")))

    def test_width_keeps_aspect_ratio(self):
        out = self.out("w200.gif")
        code, _, _ = run_cli(self.testsrc, "-o", out, "--width", "200", "--overwrite")
        self.assertEqual(code, 0)
        info = vid2gif.gif_info(out)
        self.assertEqual(info["width"], 200)
        self.assertIn(info["height"], (112, 113))  # 200 * 180 / 320 = 112.5

    def test_loop_flags(self):
        forever = self.out("forever.gif")
        once = self.out("once.gif")
        three = self.out("three.gif")
        self.assertEqual(run_cli(self.testsrc, "-o", forever, "--duration", "1")[0], 0)
        self.assertEqual(run_cli(self.testsrc, "-o", once, "--duration", "1", "--once")[0], 0)
        self.assertEqual(run_cli(self.testsrc, "-o", three, "--duration", "1", "--loop", "3")[0], 0)
        self.assertEqual(vid2gif.gif_info(forever)["loop"], 0)
        self.assertIsNone(vid2gif.gif_info(once)["loop"])
        self.assertEqual(vid2gif.gif_info(three)["loop"], 3)

    def test_start_and_duration(self):
        out = self.out("cut.gif")
        code, _, _ = run_cli(self.testsrc, "-o", out, "--start", "0.5",
                             "--duration", "1", "--fps", "10", "--overwrite")
        self.assertEqual(code, 0)
        info = vid2gif.gif_info(out)
        self.assertAlmostEqual(info["duration"], 1.0, delta=0.15)
        self.assertAlmostEqual(info["frames"], 10, delta=1)

    def test_end_option(self):
        out = self.out("end.gif")
        code, _, _ = run_cli(self.testsrc, "-o", out, "--start", "0.5", "--end", "1.5",
                             "--fps", "10", "--overwrite")
        self.assertEqual(code, 0)
        self.assertAlmostEqual(vid2gif.gif_info(out)["duration"], 1.0, delta=0.15)

    def test_dithers_and_stats_modes(self):
        for dither in vid2gif.DITHERS:
            for stats in vid2gif.STATS_MODES:
                out = self.out("d_%s_%s.gif" % (dither, stats))
                code, _, err = run_cli(self.gradient, "-o", out, "--duration", "0.5",
                                       "--width", "160", "--dither", dither,
                                       "--stats-mode", stats, "--overwrite")
                self.assertEqual(code, 0, err)
                self.assertGreater(os.path.getsize(out), 0)

    def test_bayer_scale(self):
        out = self.out("bayer.gif")
        code, _, err = run_cli(self.gradient, "-o", out, "--duration", "0.5", "--width", "160",
                               "--dither", "bayer", "--bayer-scale", "4", "--overwrite")
        self.assertEqual(code, 0, err)

    def test_fewer_colors_is_smaller(self):
        big = self.out("c256.gif")
        small = self.out("c16.gif")
        run_cli(self.testsrc, "-o", big, "--duration", "1", "--overwrite")
        run_cli(self.testsrc, "-o", small, "--duration", "1", "--colors", "16", "--overwrite")
        self.assertLess(os.path.getsize(small), os.path.getsize(big))

    def test_max_size_fits(self):
        free = self.out("free.gif")
        run_cli(self.testsrc, "-o", free, "--overwrite")
        target = os.path.getsize(free) // 3
        out = self.out("fit.gif")
        code, stdout, err = run_cli(self.testsrc, "-o", out, "--max-size", str(target),
                                    "--overwrite")
        self.assertEqual(code, 0, err)
        self.assertLessEqual(os.path.getsize(out), target)
        self.assertIn("chose:", stdout)
        self.assertEqual(vid2gif.gif_info(out)["loop"], 0)

    def test_max_size_unit_suffix(self):
        out = self.out("fitk.gif")
        code, _, err = run_cli(self.testsrc, "-o", out, "--max-size", "150K", "--overwrite")
        self.assertEqual(code, 0, err)
        self.assertLessEqual(os.path.getsize(out), 150 * 1024)

    def test_max_size_impossible(self):
        out = self.out("never.gif")
        code, _, err = run_cli(self.testsrc, "-o", out, "--max-size", "1K", "--overwrite")
        self.assertEqual(code, 3)
        self.assertIn("could not fit", err)
        self.assertFalse(os.path.exists(out))
        leftovers = [n for n in os.listdir(self.tmp) if n.endswith(".part")]
        self.assertEqual(leftovers, [])

    def test_missing_input(self):
        code, _, err = run_cli(self.out("does-not-exist.mp4"))
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_not_a_video(self):
        bad = self.out("notvideo.txt")
        with open(bad, "w") as fh:
            fh.write("hello")
        code, _, err = run_cli(bad, "-o", self.out("bad.gif"))
        self.assertEqual(code, 1)
        self.assertIn("no readable video stream", err)

    def test_start_past_end(self):
        code, _, err = run_cli(self.testsrc, "-o", self.out("late.gif"), "--start", "99")
        self.assertEqual(code, 1)
        self.assertIn("past the end", err)

    def test_refuses_to_overwrite(self):
        out = self.out("exists.gif")
        with open(out, "wb") as fh:
            fh.write(b"keep me")
        code, _, err = run_cli(self.testsrc, "-o", out)
        self.assertEqual(code, 1)
        self.assertIn("--overwrite", err)
        with open(out, "rb") as fh:
            self.assertEqual(fh.read(), b"keep me")
        self.assertEqual(run_cli(self.testsrc, "-o", out, "--duration", "0.5", "--overwrite")[0], 0)

    def test_bad_options(self):
        self.assertEqual(run_cli(self.testsrc, "--colors", "300")[0], 2)
        self.assertEqual(run_cli(self.testsrc, "--dither", "fancy")[0], 2)
        self.assertEqual(run_cli(self.testsrc, "--duration", "2", "--end", "3")[0], 2)
        self.assertEqual(run_cli(self.testsrc, "--loop", "2", "--once")[0], 2)

    def test_missing_ffmpeg(self):
        old = os.environ["PATH"]
        os.environ["PATH"] = self.tmp  # nothing useful in here
        try:
            code, _, err = run_cli(self.testsrc, "-o", self.out("nf.gif"))
        finally:
            os.environ["PATH"] = old
        self.assertEqual(code, 1)
        self.assertIn("ffmpeg", err)
        self.assertIn("install", err.lower())

    def test_launcher_script_runs(self):
        out = self.out("launcher.gif")
        res = subprocess.run([sys.executable, os.path.join(ROOT, "vid2gif"), self.testsrc,
                              "-o", out, "--duration", "0.5"],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertTrue(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
