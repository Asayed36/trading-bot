#!/bin/bash
# Runs at the start of every Claude Code cloud session (registered in .claude/settings.json).
# Installs what the video analyzer (video_analyzer/README.md) needs, only if it is missing:
#   FFmpeg (apt), yt-dlp and faster-whisper (pip). Safe to run again: it does nothing when
#   everything is already there. It never stops the session if an install fails.
# Only for the cloud sessions; on your own computer follow video_analyzer/README.md instead.
set -uo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

warn() { echo "session-start: WARNING: $*" >&2; }

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1; then
  echo "session-start: installing FFmpeg"
  # refresh the package list first (a stale list makes the install fail); some extra
  # repositories may be unreachable here, which is harmless
  apt-get update -qq >/dev/null 2>&1 || true
  apt-get install -y -qq ffmpeg >/dev/null 2>&1 || warn "FFmpeg could not be installed"
fi

missing=""
python3 -c "import yt_dlp" >/dev/null 2>&1 || missing="$missing yt-dlp"
python3 -c "import faster_whisper" >/dev/null 2>&1 || missing="$missing faster-whisper"
if [ -n "$missing" ]; then
  echo "session-start: installing$missing"
  # shellcheck disable=SC2086
  pip3 install -q $missing >/dev/null 2>&1 || warn "pip could not install:$missing"
fi

command -v ffmpeg >/dev/null 2>&1 && echo "session-start: FFmpeg ready"
python3 -c "import yt_dlp" >/dev/null 2>&1 && echo "session-start: yt-dlp ready"
python3 -c "import faster_whisper" >/dev/null 2>&1 && echo "session-start: faster-whisper ready"
exit 0
