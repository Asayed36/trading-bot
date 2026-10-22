# Project rules for Claude

## A message that is only a video link or a video file

If the user's message is **only** a video link (YouTube, Rumble, TikTok, X, Vimeo, ... any page
of one video) or **only** a path to a video file, with no other instructions, do this without
asking first:

1. **Run the analyzer** (`video_analyzer/README.md` explains the tool):
   `python video_analyzer/analyze_video.py "<link or file path>" --max-height 480 --frame-width 960` (these two options every time, once per link when several are sent; if the user wrote their own options in the message, e.g. `--max-height 720`, use theirs instead for that option).
   If it reports a missing tool, run `.claude/hooks/session-start.sh` (it installs FFmpeg,
   yt-dlp and faster-whisper) and try again.
2. **Read what it produced** in `video_analyzer/output/<video folder>/`: start with
   `timeline.md`, look at the frames that matter (charts, indicator settings, entries and
   exits on screen), and use `transcript.txt` for the exact words and times.
3. **Extract the strategy** and save it as `video_analyzer/strategies/<short-name>.md`, using
   `video_analyzer/strategies/_TEMPLATE.md` exactly (every heading, in that order).
4. **Tell the user in plain words** what the strategy is, what is missing or doubtful, and
   where the note is saved. The user is a beginner: no jargon without a short explanation.

If the message has any other instruction ("just transcribe it", "summarize", a question), follow
that instruction instead. If it is not clear that a link is a video (a repository, an article, a
channel or playlist page), ask. If several links are sent together, do each one in turn.

### Writing the note honestly

- Write only what the video actually says or shows. Put the video time next to each rule
  (e.g. `[00:04:10]`). Write **"not stated"** for anything the video does not give (exit rule,
  stop loss, position size, ...); a missing rule is a finding, not a gap to fill with a guess.
- Check every number the transcript gives against the frame on screen: speech recognition
  mishears numbers and trading words.
- In "What the video shows as proof" and "Red flags", be strict: a few winning examples, a chart
  seen with hindsight, a missing stop loss or a course being sold are not evidence. Do not
  claim anything the video's numbers do not show.
- Set the note's status to `idea`. Say how it could be tested with the existing tools
  (`backtest/` or a paper strategy). **Paper trading only: never a wallet, a private key or a
  real order.** Do not change any trading code, strategy or `config.toml` setting because of a
  video; testing an idea is a separate request.

### When the download is blocked

YouTube blocks cloud servers ("Sign in to confirm you're not a bot"), and some sites (Rumble) put
a "checking your browser" test in front of the page. When the analyzer stops with such a message:

- **Do not** try to get around it (no browser cookies or logins, no solving the test, no
  other people's mirrors) and do **not** write a strategy note from the title or the link text.
- If the cause may be this environment's network policy, check which hostnames the proxy denied
  (`curl -sS "$HTTPS_PROXY/__agentproxy/status"`, the `recentRelayFailures` list) and give the
  user the exact list to add under Allowed domains.
- Otherwise tell the user to run `video_analyzer/analyze_video.py` on their own computer, or
  to download the video in their browser, and then send the file or the contents of
  `timeline.md`. Do not claim a strategy was extracted when it was not.

### What is committed

`video_analyzer/output/` (videos, frames, audio, transcripts) is ignored by git and stays local.
Only the scripts and `video_analyzer/strategies/*.md` are committed. The repository is public:
keep private information out of the notes. Save the note and report; commit, push or open a
pull request only when the user asks.
