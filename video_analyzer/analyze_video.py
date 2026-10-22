"""Video analyzer: turns a video (YouTube, TikTok, ... or a file on your computer)
into material you can read: frames, a transcript with timestamps and a timeline.

    python video_analyzer/analyze_video.py "https://www.youtube.com/watch?v=..."
    python video_analyzer/analyze_video.py my_video.mp4
    python video_analyzer/analyze_video.py --check          # are the tools installed?

Everything goes into  video_analyzer/output/<video name>/  (never uploaded to GitHub).
Strategy notes you write from it go into  video_analyzer/strategies/  (these ARE kept).

This tool is separate from the trading bot: it reads public videos only and never uses a
wallet, a key, an order or any of the bot's files.
"""

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_ROOT = os.path.join(HERE, "output")
BLOCK_SECONDS = 30          # the timeline groups the transcript and frames in blocks of this size
DEFAULT_MAX_HEIGHT = 720        # highest video height downloaded (pixels)
DEFAULT_FRAME_WIDTH = 1280      # widest saved frame picture (pixels)
MAX_HEIGHT_RANGE = (240, 1080)
FRAME_WIDTH_RANGE = (320, 1920)
SCENE_GAP_SECONDS = 2.0     # two screen-change frames are at least this far apart (no flood when a chart flickers)
SAME_MOMENT_SECONDS = 0.5   # a screen-change frame is skipped if any frame is this close already

INSTALL_HELP = {
    "ffmpeg": ("FFmpeg is missing. Install it:\n"
               "  macOS:    brew install ffmpeg\n"
               "  Windows:  winget install ffmpeg      (then open a new terminal window)\n"
               "  Ubuntu:   sudo apt install ffmpeg"),
    "yt-dlp": "yt-dlp is missing. Install it:   pip install yt-dlp",
    "faster-whisper": "faster-whisper (Whisper) is missing. Install it:   pip install faster-whisper",
}


class ToolError(Exception):
    """A problem to show to the user in plain words (no traceback)."""


# ---------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------

def slugify(text, limit=60):
    """A safe folder name: letters, digits and dashes only."""
    text = re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-").lower()
    return (text[:limit].strip("-")) or "video"


def clock(seconds):
    """hh:mm:ss"""
    seconds = int(max(0, seconds))
    return f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"


def srt_clock(seconds):
    ms = int(round(max(0.0, seconds) * 1000))
    return f"{ms // 3600000:02d}:{(ms % 3600000) // 60000:02d}:{(ms % 60000) // 1000:02d},{ms % 1000:03d}"


def run(cmd):
    """Run a program; on failure raise ToolError with the end of its own error text."""
    try:
        done = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError:
        raise ToolError(INSTALL_HELP.get(os.path.basename(cmd[0]), f"{cmd[0]} is missing."))
    if done.returncode != 0:
        tail = "\n".join((done.stderr or done.stdout or "").strip().splitlines()[-6:])
        raise ToolError(f"{cmd[0]} failed (exit {done.returncode}):\n{tail}")
    return done


def check_tools(need_download=True, need_transcribe=True):
    """List of problems (empty when everything needed is installed)."""
    problems = []
    for tool in ("ffmpeg", "ffprobe"):
        if not shutil.which(tool):
            problems.append(INSTALL_HELP["ffmpeg"])
            break
    if need_download:
        try:
            import yt_dlp  # noqa: F401
        except ImportError:
            problems.append(INSTALL_HELP["yt-dlp"])
    if need_transcribe:
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            problems.append(INSTALL_HELP["faster-whisper"])
    return problems


# ---------------------------------------------------------------------
# 1. get the video
# ---------------------------------------------------------------------

def is_link(text):
    return bool(re.match(r"^https?://", text.strip(), re.I))


# YouTube sometimes shows "Sign in to confirm you're not a bot" to cloud servers. The default
# way of asking is tried first; if that fails, these other ways of asking (no login, no
# cookies) are tried in turn. The one that worked is remembered for the download.
FALLBACK_CLIENTS = ["android_vr", "web_safari", "tv"]


class _Quiet:
    """Keeps yt-dlp's own error lines out of the screen; we print one clear message instead."""
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


BOT_CHECK_HELP = (
    "YouTube is refusing this computer (\"Sign in to confirm you're not a bot\"). It does this "
    "to cloud servers and sometimes to home connections. What works: run this tool on your own "
    "computer (see the README), where YouTube normally allows it, or download the video "
    "yourself and give the tool the file:  python video_analyzer/analyze_video.py my_video.mp4")


SITE_BLOCK_HELP = (
    "The website is refusing automated downloads (it answered \"403 Forbidden\", usually a "
    "\"checking your browser\" test). The link itself is probably fine and opens in your browser. "
    "What works: run this tool on your own computer (see the README), or download the video "
    "yourself in your browser and give the tool the file:  "
    "python video_analyzer/analyze_video.py my_video.mp4")


def explain_failure(errors, url=""):
    """One plain message for the errors of a failed attempt (a list of exceptions or texts),
    or None when it is some other problem."""
    text = " ".join(str(e) for e in errors)
    refused = "403" in text or "Forbidden" in text or "challenge" in text.lower()
    if "not a bot" in text or (refused and _is_youtube(url)):
        return BOT_CHECK_HELP          # YouTube says it either way, depending on the try
    if refused:
        return SITE_BLOCK_HELP
    return None


def _is_youtube(url):
    return bool(re.match(r"^https?://([a-z0-9-]+\.)*(youtube\.com|youtu\.be|youtube-nocookie\.com)([/:?]|$)",
                         url.strip(), re.I))


def _options(client, **extra):
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "logger": _Quiet()}
    if client:
        opts["extractor_args"] = {"youtube": {"player_client": [client]}}
    opts.update(extra)
    return opts


def _first_line(exc):
    text = str(exc).replace("ERROR: ", "").strip()
    return text.splitlines()[0][:300] if text else type(exc).__name__


def fetch_info(url):
    """(info, client): title, id and length of the video without downloading it, and the
    way of asking that worked (None = the default). The other ways of asking are for
    YouTube only."""
    import yt_dlp
    errors = []
    for client in [None] + (FALLBACK_CLIENTS if _is_youtube(url) else []):
        try:
            with yt_dlp.YoutubeDL(_options(client, skip_download=True)) as ydl:
                return ydl.extract_info(url, download=False), client
        except Exception as exc:
            errors.append(exc)
    explained = explain_failure(errors, url)
    if explained:
        raise ToolError(explained)
    raise ToolError(f"Could not read that link: {_first_line(errors[-1])}\n"
                    "Check that it is the page of ONE video (not a channel or a playlist) and that "
                    "this computer can reach the site. If the site changed, update the "
                    "downloader:  pip install -U yt-dlp")


def check_sizes(max_height, frame_width):
    """Refuse values outside the sensible ranges, with a one-line message."""
    for name, value, (low, high), what in (
            ("--max-height", max_height, MAX_HEIGHT_RANGE, "video height"),
            ("--frame-width", frame_width, FRAME_WIDTH_RANGE, "frame picture width")):
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ToolError(f"{name} must be a whole number from {low} to {high} "
                            f"({what} in pixels), not {value!r}.")


def download_format(max_height=DEFAULT_MAX_HEIGHT):
    """yt-dlp's format choice: the best video up to `max_height` pixels high, plus the best sound."""
    return f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b"


def frame_scale(frame_width=DEFAULT_FRAME_WIDTH):
    """FFmpeg's scale filter: at most `frame_width` pixels wide, never enlarged."""
    return f"scale='min({frame_width},iw)':-2"


def download(url, folder, client=None, max_height=DEFAULT_MAX_HEIGHT):
    """Download the video (at most `max_height` pixels high, to keep files small) into
    `folder` as video.<ext>."""
    import yt_dlp
    opts = _options(client, format=download_format(max_height),
                    merge_output_format="mp4", outtmpl=os.path.join(folder, "video.%(ext)s"))
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except Exception as exc:
        raise ToolError(explain_failure([exc], url) or f"The download failed: {_first_line(exc)}")
    for name in sorted(os.listdir(folder)):
        if name.startswith("video.") and not name.endswith((".part", ".ytdl")):
            return os.path.join(folder, name)
    raise ToolError("The download finished but no video file was found.")


def duration_seconds(video):
    done = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1", video])
    try:
        return float(done.stdout.strip())
    except ValueError:
        raise ToolError("Could not read the length of the video (is it a real video file?).")


# ---------------------------------------------------------------------
# 2. frames
# ---------------------------------------------------------------------

def scene_change_times(video, threshold):
    """Seconds at which the picture changes a lot (FFmpeg's scene detection; a lower
    threshold finds more changes)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", video, "-an", "-vf",
           f"scale=320:-2,select='gt(scene,{threshold})',showinfo", "-f", "null", "-"]
    done = run(cmd)
    return [float(m) for m in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", done.stderr)]


def plan_frame_times(duration, interval, scene_times, max_frames):
    """[(second, reason)] sorted: one frame every `interval` seconds, plus a frame at each
    screen change (unless a frame is already within SAME_MOMENT_SECONDS, or another
    screen-change frame within SCENE_GAP_SECONDS). If there are more than `max_frames`, an
    evenly spread subset is kept. Returns (plan, thinned)."""
    plan, t = [], 0.0
    while t < duration - 0.05:
        plan.append((round(t, 2), "every %gs" % interval))
        t += interval
    every = [p[0] for p in plan]
    kept_scenes = []
    for s in sorted(scene_times):
        if s >= duration - 0.05:
            continue
        if any(abs(s - x) < SAME_MOMENT_SECONDS for x in every + kept_scenes):
            continue
        if any(abs(s - x) < SCENE_GAP_SECONDS for x in kept_scenes):
            continue
        kept_scenes.append(s)
    plan += [(round(s, 2), "screen changed") for s in kept_scenes]
    plan.sort()
    thinned = len(plan) > max_frames
    if thinned:
        step = len(plan) / max_frames
        plan = [plan[int(i * step)] for i in range(max_frames)]
    return plan, thinned


def frame_name(number, seconds):
    s = int(seconds)
    return f"frame_{number:04d}_t{s // 3600:02d}-{(s % 3600) // 60:02d}-{s % 60:02d}.jpg"


def extract_frames(video, folder, plan, say=print, frame_width=DEFAULT_FRAME_WIDTH):
    """Save one picture per planned second; returns [{file, seconds, time, reason}]."""
    os.makedirs(folder, exist_ok=True)
    frames = []
    for i, (t, reason) in enumerate(plan, 1):
        name = frame_name(i, t)
        path = os.path.join(folder, name)
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{t:.3f}", "-i", video,
             "-frames:v", "1", "-vf", frame_scale(frame_width), "-q:v", "3", path])
        if os.path.exists(path):
            frames.append({"file": name, "seconds": t, "time": clock(t), "reason": reason})
        if i % 50 == 0:
            say(f"    {i} of {len(plan)} frames saved")
    with open(os.path.join(folder, "index.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["file", "seconds", "time", "reason"])
        w.writeheader()
        w.writerows(frames)
    return frames


# ---------------------------------------------------------------------
# 3. audio and transcript
# ---------------------------------------------------------------------

def extract_audio(video, path):
    """Mono 16 kHz WAV (what Whisper wants). Returns False when the video has no sound."""
    probe = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                 "stream=index", "-of", "csv=p=0", video])
    if not probe.stdout.strip():
        return False
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", video, "-vn", "-ac", "1",
         "-ar", "16000", path])
    return True


def transcribe(audio, model_name="base", language=None, model_factory=None):
    """Whisper (faster-whisper, on the CPU) -> (segments, language) where each segment is
    {start, end, text}. The first run downloads the model (base is about 140 MB)."""
    if model_factory is None:
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ToolError(INSTALL_HELP["faster-whisper"])

        def model_factory(name):
            return WhisperModel(name, device="cpu", compute_type="int8")
    try:
        model = model_factory(model_name)
        segments, info = model.transcribe(audio, language=language, vad_filter=True)
        out = [{"start": float(s.start), "end": float(s.end), "text": s.text.strip()}
               for s in segments if s.text.strip()]
    except ToolError:
        raise
    except Exception as exc:
        raise ToolError(f"Transcription failed: {str(exc)[-300:]}\n"
                        "(The first run needs internet to download the Whisper model.)")
    return out, getattr(info, "language", language)


def write_transcripts(folder, segments, language):
    with open(os.path.join(folder, "transcript.txt"), "w") as fh:
        for s in segments:
            fh.write(f"[{clock(s['start'])}] {s['text']}\n")
    with open(os.path.join(folder, "transcript.srt"), "w") as fh:
        for i, s in enumerate(segments, 1):
            fh.write(f"{i}\n{srt_clock(s['start'])} --> {srt_clock(s['end'])}\n{s['text']}\n\n")
    with open(os.path.join(folder, "transcript.json"), "w") as fh:
        json.dump({"language": language, "segments": segments}, fh, indent=1)


# ---------------------------------------------------------------------
# 4. the timeline (the file to read, or to give to Claude)
# ---------------------------------------------------------------------

def build_timeline(meta, segments, frames, block=BLOCK_SECONDS):
    lines = [f"# {meta.get('title') or 'Video'}", ""]
    for key, label in (("source", "Source"), ("uploader", "Channel"), ("duration", "Length"),
                       ("language", "Spoken language"), ("analyzed", "Analyzed")):
        if meta.get(key):
            lines.append(f"- {label}: {meta[key]}")
    lines += [f"- Frames saved: {len(frames)} (in `frames/`, list in `frames/index.csv`)",
              f"- Transcript pieces: {len(segments)} (`transcript.txt`, `.srt`, `.json`)", "",
              "Read this top to bottom. Each block is 30 seconds: what was said, then the frames "
              "taken in that block (open them to see the chart or screen at that moment).", ""]
    end = max([s["end"] for s in segments] + [f["seconds"] for f in frames] + [0])
    for start in range(0, int(end) + 1, block):
        said = [s for s in segments if start <= s["start"] < start + block]
        shown = [f for f in frames if start <= f["seconds"] < start + block]
        if not said and not shown:
            continue
        lines.append(f"## {clock(start)} - {clock(start + block)}")
        if said:
            lines.append("")
            lines.append(" ".join(s["text"] for s in said))
        for f in shown:
            lines.append(f"- Frame {f['time']} ({f['reason']}): `frames/{f['file']}`")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# the whole job
# ---------------------------------------------------------------------

def analyze(source, output_root=OUTPUT_ROOT, interval=5.0, scene_threshold=0.3, max_frames=600,
            model="base", language=None, do_frames=True, do_transcribe=True, say=print,
            transcriber=transcribe, max_height=DEFAULT_MAX_HEIGHT, frame_width=DEFAULT_FRAME_WIDTH):
    """Run every step for a link or a video file. Returns the output folder."""
    check_sizes(max_height, frame_width)
    problems = check_tools(need_download=is_link(source), need_transcribe=do_transcribe)
    if problems:
        raise ToolError("\n\n".join(problems))

    say("Step 1/5: finding the video")
    meta = {"analyzed": datetime.now().strftime("%Y-%m-%d %H:%M")}
    client = None
    if is_link(source):
        info, client = fetch_info(source)
        name = slugify(info.get("title")) + "-" + slugify(info.get("id"), 20)
        meta.update(title=info.get("title"), source=source, uploader=info.get("uploader"))
    else:
        if not os.path.isfile(source):
            raise ToolError(f"No such file: {source}")
        name = slugify(os.path.splitext(os.path.basename(source))[0])
        meta.update(title=os.path.basename(source), source=os.path.abspath(source))
    folder = os.path.join(output_root, name)
    os.makedirs(folder, exist_ok=True)
    say(f"  Folder: {folder}")

    say("Step 2/5: downloading" if is_link(source) else "Step 2/5: using the file you gave (no download)")
    video = download(source, folder, client, max_height) if is_link(source) else os.path.abspath(source)
    duration = duration_seconds(video)
    meta["duration"] = clock(duration)
    say(f"  Length: {meta['duration']}")

    frames = []
    if do_frames:
        say("Step 3/5: finding the moments where the screen changes, then saving frames")
        scenes = scene_change_times(video, scene_threshold)
        plan, thinned = plan_frame_times(duration, interval, scenes, max_frames)
        if thinned:
            say(f"  Note: more than {max_frames} frames were planned, so an evenly spread "
                f"{max_frames} are kept (use --interval with a bigger number for fewer).")
        say(f"  {len(plan)} frames planned ({len(scenes)} screen changes found)")
        frames = extract_frames(video, os.path.join(folder, "frames"), plan, say, frame_width)
    else:
        say("Step 3/5: skipped (frames)")

    segments = []
    if do_transcribe:
        say("Step 4/5: pulling out the sound and writing the transcript (the slow step)")
        audio = os.path.join(folder, "audio.wav")
        if extract_audio(video, audio):
            segments, lang = transcriber(audio, model, language)
            meta["language"] = lang
            write_transcripts(folder, segments, lang)
            say(f"  {len(segments)} transcript pieces, language: {lang}")
        else:
            say("  This video has no sound, so there is no transcript.")
    else:
        say("Step 4/5: skipped (transcript)")

    say("Step 5/5: writing the timeline")
    with open(os.path.join(folder, "timeline.md"), "w") as fh:
        fh.write(build_timeline(meta, segments, frames))
    with open(os.path.join(folder, "metadata.json"), "w") as fh:
        json.dump(dict(meta, interval_seconds=interval, scene_threshold=scene_threshold,
                       model=model, max_height=max_height, frame_width=frame_width,
                       frames=len(frames), segments=len(segments)), fh, indent=1)
    return folder


def main(argv=None):
    p = argparse.ArgumentParser(description="Download a video, save frames and a transcript.")
    p.add_argument("source", nargs="?", help="a video link (YouTube, TikTok, ...) or a video file")
    p.add_argument("--check", action="store_true", help="only check that the tools are installed")
    p.add_argument("--interval", type=float, default=5.0, help="seconds between frames (default 5)")
    p.add_argument("--scene-threshold", type=float, default=0.3,
                   help="0-1; lower saves more extra frames when the screen changes (default 0.3)")
    p.add_argument("--max-frames", type=int, default=600, help="most frames to save (default 600)")
    p.add_argument("--model", default="base", help="Whisper model: tiny, base, small ... (default base)")
    p.add_argument("--language", default=None, help="spoken language code, e.g. en (default: detect)")
    p.add_argument("--max-height", type=int, default=DEFAULT_MAX_HEIGHT,
                   help="highest video height to download, %d-%d (default %d)"
                   % (*MAX_HEIGHT_RANGE, DEFAULT_MAX_HEIGHT))
    p.add_argument("--frame-width", type=int, default=DEFAULT_FRAME_WIDTH,
                   help="widest saved frame picture, %d-%d (default %d)"
                   % (*FRAME_WIDTH_RANGE, DEFAULT_FRAME_WIDTH))
    p.add_argument("--no-frames", action="store_true", help="skip the frames")
    p.add_argument("--no-transcript", action="store_true", help="skip the transcript")
    p.add_argument("--output", default=OUTPUT_ROOT, help="where to put the video folder")
    args = p.parse_args(argv)
    try:
        if args.check:
            problems = check_tools()
            print("\n\n".join(problems) if problems else "Everything is installed: FFmpeg, yt-dlp, Whisper.")
            return 1 if problems else 0
        if not args.source:
            p.print_help()
            return 2
        if args.interval <= 0 or args.max_frames <= 0:
            raise ToolError("--interval and --max-frames must be bigger than 0.")
        folder = analyze(args.source, args.output, args.interval, args.scene_threshold,
                         args.max_frames, args.model, args.language,
                         not args.no_frames, not args.no_transcript,
                         max_height=args.max_height, frame_width=args.frame_width)
    except ToolError as exc:
        print(f"\nStopped: {exc}", file=sys.stderr)
        return 1
    print(f"\nDone. Everything is in:\n  {folder}\nStart with timeline.md. "
          "Strategy notes go into video_analyzer/strategies/ (see its _TEMPLATE.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
