# Video analyzer

Turns a trading video (YouTube, TikTok, ... or a file on your computer) into things you can
read: **pictures of the screen**, **what was said, with times**, and one **timeline** that
puts them together. You then work through it with Claude and write down any strategy as a
short note. This folder is separate from the trading bot: it never touches the bot's code,
settings or data, and uses no wallet, key or order.

## One-time setup (on your own computer)

You need Python 3.10+, and the project downloaded (`git clone`) so this folder is there.

1. **FFmpeg** (cuts the video into pictures and sound):
   - Mac: `brew install ffmpeg`
   - Windows: `winget install ffmpeg` (then open a new terminal window)
   - Ubuntu/Linux: `sudo apt install ffmpeg`
2. **The two Python tools** (run this in the project folder):
   `pip install -r video_analyzer/requirements.txt`
   - `yt-dlp` downloads videos. `faster-whisper` is the Whisper speech-to-text model
     in a version that runs fast on a normal computer (no graphics card needed).
3. Check: `python video_analyzer/analyze_video.py --check` should say everything is installed.

The first transcript downloads the Whisper "base" model (about 140 MB, once).

## Use it

    python video_analyzer/analyze_video.py "https://www.youtube.com/watch?v=XXXX"
    python video_analyzer/analyze_video.py my_video.mp4

It prints each step as it goes. When it finishes it shows the folder, e.g.
`video_analyzer/output/<video-name>-<id>/`:

| File | What it is |
|---|---|
| `timeline.md` | **Start here.** 30-second blocks: what was said, and the frames taken in that block |
| `frames/` | A picture every 5 seconds, plus extra ones when the screen changes (`frames/index.csv` lists the times) |
| `transcript.txt` / `.srt` / `.json` | The words with timestamps |
| `video.mp4`, `audio.wav` | The download and the sound (kept so you can re-run without downloading) |
| `metadata.json` | Title, link, length and the settings used |

Useful options: `--interval 10` (a frame every 10 s instead of 5), `--scene-threshold 0.2`
(more extra frames when the screen changes; higher = fewer), `--model small` (better
transcript, slower), `--language en`, `--no-frames`, `--no-transcript`, `--max-frames 300`.
A long video makes many frames; if it plans more than `--max-frames` (600) it keeps an
evenly spread selection and tells you.

Size options: `--max-height` (highest video height to download, 240 to 1080, default 720) and
`--frame-width` (widest saved frame picture, 320 to 1920, default 1280). Lower numbers make
smaller files, but charts and small text get harder to read; `--max-height 480
--frame-width 960` is a good size for talking videos. Both are saved in `metadata.json`.

## Working on a video with Claude

1. Run the script on your computer (Claude's cloud session cannot reach YouTube).
2. Open Claude Code **in the project folder on your computer**, so it can read
   `video_analyzer/output/<video>/timeline.md` and look at the frame pictures. (Or paste the
   timeline into the chat.)
3. Ask Claude to pull out the rules and write them into
   `video_analyzer/strategies/<name>.md`, using `strategies/_TEMPLATE.md`.
4. To test an idea, ask Claude to run it through the bot's `backtest/` tool or a paper
   strategy, with the usual fixed rules and costs. **Paper trading only.**

## Read this before trusting a video

A video shows what its maker chose to show. Winning examples, a chart seen with hindsight
or a missing stop loss are not evidence. The template asks for the proof shown and the red
flags for this reason. Treat every extracted strategy as an idea to test, not a result. A
transcript can also mishear numbers, so check any figure against the frame on screen.

## What is and is not uploaded to GitHub

`.gitignore` keeps `video_analyzer/output/` (videos, frames, audio, transcripts) and any
video, audio or picture file anywhere in this folder **on your computer only**. Only the
scripts, this README and `strategies/*.md` are committed. Do not put private information in
the strategy notes: the repository is public.

Please only analyze videos you are allowed to watch, for your own study, and do not
re-share the downloaded files.

## Tests

    python -m unittest discover -s video_analyzer/tests -v

These are separate from the bot's tests and are not run by its workflows.
