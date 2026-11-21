# FAST_PRD: Same-Day Local GTA 6 Gaming Clipper

## Goal

Build a fast, 100% local Python + Gradio web app for Windows (16 GB RAM, CPU-first) that turns long gaming VODs (local MP4/MKV or yt-dlp URL) into ranked, ready-to-post 9:16 vertical clips with animated captions.

## Stack & Strict Constraints

- Python 3.11+, Gradio UI (`app.py`), SQLite (`db.py`)
- Pin `av<16` for `faster-whisper` on Windows to avoid PyAV crashes.
- FFmpeg / ffprobe subprocesses for all media cutting, reframing, and caption burning.
- Local Ollama (`qwen2.5:3b`) optional: auto-detect if running on `localhost:11434`; if not, automatically fall back to heuristic scoring with zero errors.
- Keep every module under 250 lines.

## Modules to Build

1. `ingest.py`: Accept local video path or `yt-dlp` URL; run `ffprobe` for duration/resolution; extract 16kHz mono WAV for fast analysis.
2. `signals.py`:
   - `faster-whisper` (`small`, `int8`, CPU) word-level transcription + Silero VAD.
   - Audio RMS excitement peaks (`numpy`/`librosa`) in 3-second rolling windows.
   - Optional chat-log parser (TwitchDownloader JSON, `yt-dlp` `.live_chat.json`, or `[HH:MM:SS]` TXT) with rolling-baseline spike detection and spam filtering.
3. `ranker.py`:
   - Combine normalised signals (`0.35*Chat + 0.30*Audio + 0.35*Transcript/Ollama`, auto-reweighted if chat or Ollama is missing).
   - Accept a user prompt (e.g. "GTA 6 funny fails, chases, crazy reactions, 30-45s") and duration preset (`15s`, `30s`, `45s`, `60s`, `Auto`).
   - Return top N non-overlapping intervals padded to sentence boundaries, each labelled `chat_assisted` or `ai_estimated` with a plain-English `reason`.
4. `render.py`:
   - 3 quick layouts: **Gaming Split-Screen** (top facecam crop + bottom gameplay), **Full 9:16 Center/Face Crop** (MediaPipe EMA-smoothed), and **16:9 Clean**.
   - Generate word-level animated `.ass` subtitles (bold yellow/white active-word highlight inside mobile-safe margins) and burn with FFmpeg `H.264 + AAC` + loudnorm audio.
5. `app.py` (Gradio UI):
   - Tab 1: Upload/URL + optional chat log + Prompt + Duration + "Find Highlights".
   - Tab 2: Candidate list with video preview, timestamps, editable start/end sliders, editable caption text, evidence badge + reason, layout selector, and "Render Selected / Batch Export".
