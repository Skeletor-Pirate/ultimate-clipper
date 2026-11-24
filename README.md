# Ultimate GTA 6 Gaming Clipper 🎮⚡

A 100% local-first, privacy-respecting gaming highlight detection & vertical clipper web app built with Python, Gradio, Faster-Whisper, and FFmpeg.

Inspired by viral gaming channels (**@sky_aep77**, **@the360gamer_**, **@ai_game_zone**, **@mrbeastclips**) and designed to produce transformative, YouTube monetization-compliant Shorts & Reels.

---

## ✨ Features

- **🎬 4 Layout Modes**:
  - `50/50 Facecam + Gameplay Split (9:16)`: Top half naturally frames the streamer facecam over ambient blurred padding (no over-zoomed cutoffs) separated by a glowing seam divider line from the bottom gameplay.
  - `Center 9:16 Crop`: Direct vertical framing for action-centric sequences.
  - `Picture-in-Picture (Facecam Overlay)`: Scaled streamer facecam cleanly composited over full gameplay.
  - `Fit with Blurred Background (9:16)`: Preserves uncropped 16:9 gameplay with cinematic blurred background fill.

- **💬 Middle-Split Karaoke Subtitles**:
  - Positioned directly on the seam line between facecam and gameplay (inspired by `RCCKsDDA_QI` and `sky_aep77`).
  - Word-level active karaoke highlighting (`PlayResY=1920`, `MarginV=925`).
  - Automatic YouTube sound effect cues & sentiment emojis:
    - Non-speech & vocal reactions: `*HEAVY BREATHING* 😮‍💨`, `*GASP* 😱`, `*LAUGHING* 😂`, `*INTENSE MOMENT* ⚡`.
    - Keyword sentiment mappings for gaming reactions (kills, crashes, hype moments, police chases).

- **🎵 Background Music Integration & Audio Ducking**:
  - Upload custom background tracks (`.mp3`, `.wav`, `.m4a`).
  - Automatic looping and volume ducking beneath speech.
  - EBU R128 loudness normalization (`loudnorm=I=-16:TP=-1.5:LRA=11`) to prevent clipping and match platform broadcast standards.

- **🚀 Multi-Clip Generation (5 to 10 Clips per Round)**:
  - Configurable slider to create 5, 8, 10, or up to 15 non-overlapping highlight clips in a single round.
  - Batch render all clips at once with interactive exported clips gallery.

- **🎨 Built-in Creator Assets & Editing Hub**:
  - Direct in-app directory linking to 26+ curated free resources:
    - **VFX Overlays**: FX Elements (4K alpha), FootageCrate, PRADUMNA_FX, Video Effect Vibe.
    - **Editing Templates**: Mixkit, Videezy, PremiumBeat Toolkit, Clipchamp.
    - **Emojis & Stickers**: Emoji Island, Icons8, Streamline, Flaticon, StickPNG, LightX.
    - **Creator Sound Effects**: Mixkit SFX, Uppbeat, Signature Sounds CC0, Epic Whooshes.
    - **Open-Source Repositories**: Fluent UI Emoji, OpenMoji, Twemoji, Noto Emoji, Meta Open Sound.
  - See full documentation in [CREATOR_ASSETS.md](CREATOR_ASSETS.md).

- **⚡ Fast Seeking & Local Processing**:
  - Fast input seeking (`-ss` before `-i`) for near-instant rendering even on 2-hour VODs.
  - 100% local operation: runs on CPU (16 GB RAM friendly) with graceful fallback if Ollama is offline.
  - Windows drive path escaping (`replace(':', r'\:')`) for robust FFmpeg ASS subtitle rendering.

---

## 🛠️ Quickstart

### 1. Requirements
- Python 3.10+ (tested on Python 3.14)
- [FFmpeg](https://ffmpeg.org/) installed and added to `PATH`
- (Optional) [Ollama](https://ollama.ai/) with `llama3.2:latest` for AI commentary ranking (heuristic fallback automatically active if offline)

### 2. Installation
```bash
pip install -r requirements.txt
```

### 3. Launch Web App
```bash
python app.py
```
Open your browser at `http://127.0.0.1:7860/`.

---

## 🧪 Testing

Run the full pytest suite:
```bash
pytest test_step1.py test_step2.py test_step3.py
```
All 17 tests verify ingestion, audio extraction, transcription caching, heuristic scoring, ASS subtitle formatting, and Gradio interface pipelines.

---

## 📁 Project Architecture

- `ingest.py`: Download engine & local file validator with fast 16kHz mono audio extraction.
- `signals.py`: Transcription pipeline via Faster-Whisper with word-level timestamps and energy signal extraction.
- `ranker.py`: Peak detection, non-overlapping window merging, and Ollama LLM / heuristic scoring.
- `render.py`: High-performance FFmpeg rendering engine with split-screen compositing, middle-split ASS subtitle generation, and background audio mixing.
- `assets_hub.py`: Curated creator directory for video effects, SFX, emojis, stickers, and templates.
- `app.py`: Modern Gradio web UI with interactive clip review, batch export, and creator assets hub.
