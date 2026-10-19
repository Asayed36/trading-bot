"""Checks for video_analyzer/analyze_video.py. Run with:
    python -m unittest discover -s video_analyzer/tests -v
Not part of the bot's test suite. The real frame cutting and scene detection use FFmpeg on a
tiny made-up video; the transcript step uses a stand-in (the real Whisper model needs a download)."""

import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import analyze_video as av  # noqa: E402

HAVE_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def make_video(path, silent=False):
    """12 s: black for 6 s, then white; with a tone unless silent."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "lavfi", "-i", "color=c=black:s=320x240:r=10:d=6",
           "-f", "lavfi", "-i", "color=c=white:s=320x240:r=10:d=6"]
    if not silent:
        cmd += ["-f", "lavfi", "-i", "sine=frequency=440:duration=12"]
    cmd += ["-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0[v]", "-map", "[v]"]
    if not silent:
        cmd += ["-map", "2:a"]
    subprocess.run(cmd + ["-pix_fmt", "yuv420p", path], check=True)


class HelperTests(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(av.slugify("My Strategy: 10x in 5 min!! (REAL)"), "my-strategy-10x-in-5-min-real")
        self.assertEqual(av.slugify("../../etc/passwd"), "etc-passwd")
        self.assertEqual(av.slugify("???"), "video")
        self.assertEqual(av.slugify(None), "video")
        self.assertLessEqual(len(av.slugify("a" * 200)), 60)

    def test_clocks(self):
        self.assertEqual(av.clock(0), "00:00:00")
        self.assertEqual(av.clock(3725.9), "01:02:05")
        self.assertEqual(av.srt_clock(3725.5), "01:02:05,500")

    def test_is_link(self):
        self.assertTrue(av.is_link("https://youtu.be/abc"))
        self.assertTrue(av.is_link("http://tiktok.com/x"))
        self.assertFalse(av.is_link("video.mp4"))

    def test_frame_name_has_the_time(self):
        self.assertEqual(av.frame_name(7, 3725), "frame_0007_t01-02-05.jpg")


class PlanTests(unittest.TestCase):
    def test_regular_frames_plus_screen_changes(self):
        plan, thinned = av.plan_frame_times(12, 5, [6.0], 600)
        self.assertIn((6.0, "screen changed"), plan)
        self.assertEqual([t for t, r in plan if r.startswith("every")], [0.0, 5.0, 10.0])
        self.assertFalse(thinned)

    def test_screen_changes_are_spaced_and_not_doubled_up(self):
        plan, _ = av.plan_frame_times(12, 5, [5.2, 6.0, 7.5, 8.2], 600)
        scene = [t for t, r in plan if r == "screen changed"]
        # 5.2 is within 0.5 s of the frame at 5.0; 7.5 is within 2 s of the kept 6.0
        self.assertEqual(scene, [6.0, 8.2])

    def test_scene_changes_past_the_end_are_ignored(self):
        plan, _ = av.plan_frame_times(10, 5, [9.99, 50], 600)
        self.assertEqual([t for t, _ in plan], [0.0, 5.0])

    def test_too_many_frames_are_thinned_evenly(self):
        plan, thinned = av.plan_frame_times(1000, 1, [], 100)
        self.assertTrue(thinned)
        self.assertEqual(len(plan), 100)
        self.assertEqual(plan, sorted(plan))
        self.assertEqual(plan[0][0], 0.0)


class OutputTests(unittest.TestCase):
    SEGMENTS = [{"start": 1.0, "end": 4.0, "text": "Buy when the price breaks the high."},
                {"start": 35.0, "end": 40.5, "text": "Stop loss is below the low."}]
    FRAMES = [{"file": "frame_0001_t00-00-00.jpg", "seconds": 0.0, "time": "00:00:00", "reason": "every 5s"},
              {"file": "frame_0002_t00-00-36.jpg", "seconds": 36.0, "time": "00:00:36",
               "reason": "screen changed"}]

    def test_transcript_files(self):
        with tempfile.TemporaryDirectory() as d:
            av.write_transcripts(d, self.SEGMENTS, "en")
            txt = open(os.path.join(d, "transcript.txt")).read().splitlines()
            self.assertEqual(txt[0], "[00:00:01] Buy when the price breaks the high.")
            srt = open(os.path.join(d, "transcript.srt")).read()
            self.assertIn("1\n00:00:01,000 --> 00:00:04,000\nBuy when", srt)
            data = json.load(open(os.path.join(d, "transcript.json")))
            self.assertEqual((data["language"], len(data["segments"])), ("en", 2))

    def test_timeline_groups_speech_and_frames_in_30_second_blocks(self):
        text = av.build_timeline({"title": "T", "source": "https://x", "duration": "00:00:41"},
                                 self.SEGMENTS, self.FRAMES)
        self.assertIn("# T", text)
        first, second = text.split("## 00:00:30 - 00:01:00")
        self.assertIn("## 00:00:00 - 00:00:30", first)
        self.assertIn("Buy when the price breaks the high.", first)
        self.assertIn("`frames/frame_0001_t00-00-00.jpg`", first)
        self.assertIn("Stop loss is below the low.", second)
        self.assertIn("(screen changed)", second)

    def test_timeline_without_speech(self):
        text = av.build_timeline({"title": "Silent"}, [], self.FRAMES)
        self.assertIn("Transcript pieces: 0", text)
        self.assertIn("frame_0002", text)


class ToolCheckTests(unittest.TestCase):
    def test_missing_tools_give_install_help(self):
        with mock.patch.object(av.shutil, "which", return_value=None):
            problems = av.check_tools(need_download=False, need_transcribe=False)
        self.assertEqual(len(problems), 1)
        self.assertIn("brew install ffmpeg", problems[0])

    def test_missing_program_is_a_plain_error(self):
        with self.assertRaises(av.ToolError) as ctx:
            av.run(["definitely-not-a-program-xyz"])
        self.assertIn("missing", str(ctx.exception))

    def test_bad_file_is_a_plain_error(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(av.ToolError) as ctx:
                av.analyze(os.path.join(d, "nope.mp4"), d, do_transcribe=False, say=lambda *a: None)
            self.assertIn("No such file", str(ctx.exception))

    def test_bad_options_are_refused(self):
        self.assertEqual(av.main(["x.mp4", "--interval", "0"]), 1)
        self.assertEqual(av.main([]), 2)


@unittest.skipUnless(HAVE_FFMPEG, "needs FFmpeg")
class EndToEndTests(unittest.TestCase):
    """A made-up local video through every step. The transcript is a stand-in."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.video = os.path.join(self.tmp.name, "My Test Video.mp4")
        make_video(self.video)
        self.out = os.path.join(self.tmp.name, "out")

    @staticmethod
    def fake_transcriber(audio, model, language):
        assert audio.endswith("audio.wav") and os.path.getsize(audio) > 1000
        return [{"start": 2.0, "end": 5.0, "text": "stand-in words"}], "en"

    def test_everything_is_saved_in_a_folder_named_after_the_video(self):
        say = []
        folder = av.analyze(self.video, self.out, interval=5, say=say.append,
                            transcriber=self.fake_transcriber)
        self.assertEqual(os.path.basename(folder), "my-test-video")
        names = set(os.listdir(folder))
        self.assertTrue({"audio.wav", "frames", "timeline.md", "metadata.json", "transcript.txt",
                         "transcript.srt", "transcript.json"} <= names)
        self.assertNotIn("video.mp4", names)               # a local file is not copied
        with open(os.path.join(folder, "frames", "index.csv")) as fh:
            rows = list(csv.DictReader(fh))
        files = os.listdir(os.path.join(folder, "frames"))
        self.assertEqual(sum(f.endswith(".jpg") for f in files), len(rows))
        reasons = {r["reason"] for r in rows}
        self.assertIn("every 5s", reasons)
        scene = [float(r["seconds"]) for r in rows if r["reason"] == "screen changed"]
        self.assertTrue(scene and abs(scene[0] - 6.0) < 0.5, scene)      # the black -> white cut
        self.assertEqual([float(r["seconds"]) for r in rows if r["reason"] == "every 5s"], [0.0, 5.0, 10.0])
        meta = json.load(open(os.path.join(folder, "metadata.json")))
        self.assertEqual((meta["frames"], meta["segments"], meta["duration"]), (len(rows), 1, "00:00:12"))
        self.assertIn("stand-in words", open(os.path.join(folder, "timeline.md")).read())
        self.assertTrue(any("Step 5/5" in s for s in say))

    def test_a_video_without_sound_has_no_transcript_and_no_crash(self):
        silent = os.path.join(self.tmp.name, "silent.mp4")
        make_video(silent, silent=True)
        folder = av.analyze(silent, self.out, say=lambda *a: None,
                            transcriber=lambda *a: self.fail("must not be called"))
        self.assertNotIn("transcript.txt", os.listdir(folder))
        self.assertIn("timeline.md", os.listdir(folder))

    def test_frames_and_transcript_can_be_skipped(self):
        folder = av.analyze(self.video, self.out, do_frames=False, do_transcribe=False,
                            say=lambda *a: None)
        self.assertEqual(sorted(os.listdir(folder)), ["metadata.json", "timeline.md"])

    def test_the_command_line_runs(self):
        code = av.main([self.video, "--output", self.out, "--no-transcript", "--interval", "6"])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.isdir(os.path.join(self.out, "my-test-video", "frames")))


class FetchInfoTests(unittest.TestCase):
    """fetch_info with a stand-in for yt-dlp: which way of asking is tried, in what order."""

    def fake_module(self, works_with):
        tried = []

        class YDL:
            def __init__(self, opts):
                self.client = (opts.get("extractor_args", {}).get("youtube", {})
                               .get("player_client") or [None])[0]
                tried.append(self.client)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def extract_info(self, url, download=False):
                if self.client in works_with:
                    return {"title": "T", "id": "abc"}
                raise RuntimeError("ERROR: [youtube] abc: Sign in to confirm you\u2019re not a bot. "
                                   "Use --cookies-from-browser")
        return SimpleNamespace(YoutubeDL=YDL), tried

    def test_the_default_way_is_tried_first_then_the_others_in_order(self):
        module, tried = self.fake_module(works_with=["web_safari"])
        with mock.patch.dict(sys.modules, {"yt_dlp": module}):
            info, client = av.fetch_info("https://youtu.be/abc")
        self.assertEqual((info["title"], client), ("T", "web_safari"))
        self.assertEqual(tried, [None, "android_vr", "web_safari"])

    def test_no_fallback_when_the_default_works(self):
        module, tried = self.fake_module(works_with=[None])
        with mock.patch.dict(sys.modules, {"yt_dlp": module}):
            _, client = av.fetch_info("https://youtu.be/abc")
        self.assertEqual((client, tried), (None, [None]))

    def test_the_bot_check_message_wins_even_if_the_last_try_failed_differently(self):
        module, _ = self.fake_module(works_with=[])
        original = module.YoutubeDL.extract_info

        def extract(self, url, download=False):
            if self.client == "tv":
                raise RuntimeError("The page needs to be reloaded.")
            return original(self, url, download)
        module.YoutubeDL.extract_info = extract
        with mock.patch.dict(sys.modules, {"yt_dlp": module}):
            with self.assertRaises(av.ToolError) as ctx:
                av.fetch_info("https://youtu.be/abc")
        self.assertEqual(str(ctx.exception), av.BOT_CHECK_HELP)

    def test_the_bot_check_gives_one_clear_message(self):
        module, tried = self.fake_module(works_with=[])
        with mock.patch.dict(sys.modules, {"yt_dlp": module}):
            with self.assertRaises(av.ToolError) as ctx:
                av.fetch_info("https://youtu.be/abc")
        self.assertEqual(str(ctx.exception), av.BOT_CHECK_HELP)
        self.assertIn("your own computer", str(ctx.exception))
        self.assertEqual(len(tried), 1 + len(av.FALLBACK_CLIENTS))


class TranscribeTests(unittest.TestCase):
    def test_segments_are_cleaned_and_the_language_is_reported(self):
        seg = lambda a, b, t: SimpleNamespace(start=a, end=b, text=t)           # noqa: E731

        class Model:
            def transcribe(self, audio, language=None, vad_filter=False):
                assert vad_filter is True
                return [seg(0, 1, "  hello "), seg(1, 2, "   ")], SimpleNamespace(language="en")
        out, lang = av.transcribe("a.wav", "base", None, model_factory=lambda name: Model())
        self.assertEqual((out, lang), ([{"start": 0.0, "end": 1.0, "text": "hello"}], "en"))

    def test_a_failing_model_is_a_plain_error(self):
        def broken(name):
            raise OSError("no internet")
        with self.assertRaises(av.ToolError) as ctx:
            av.transcribe("a.wav", "base", None, model_factory=broken)
        self.assertIn("download the Whisper model", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
