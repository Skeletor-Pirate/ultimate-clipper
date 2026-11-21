"""app.py: 100% local Gradio web UI for Same-Day GTA 6 Gaming Clipper.
Features fast seeking, middle-split animated ASS captions, background music, and batch export.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import gradio as gr

from ingest import ingest_source
from signals import compute_audio_energy, parse_chat_log, transcribe_audio
from ranker import rank_highlights
from render import render_clip

LAYOUT_MAP = {"Gaming Split-Screen (9:16)": "gaming_split", "Fit with Blurred Background (9:16)": "blur_fit", "Full Center Crop (9:16)": "full_9_16", "16:9 Clean": "clean_16_9"}
CORNER_MAP = {"Bottom-Left": "bottom-left", "Bottom-Center": "bottom-center", "Bottom-Right": "bottom-right", "Top-Left": "top-left", "Top-Center": "top-center", "Top-Right": "top-right"}
EXPORTS_DIR = Path("exports").resolve()
EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def on_find_highlights(
    source_input: str,
    chat_file: Optional[Any],
    prompt: str,
    duration_preset: str,
    progress: gr.Progress = gr.Progress(),
) -> tuple[str, Any, float, float, str, str, Dict[str, Any]]:
    """Process ingestion, extract signals, and rank highlight intervals with robust error handling."""
    if not source_input or not source_input.strip():
        msg = "❌ Please enter a local video file path or URL."
        gr.Warning(msg)
        return msg, gr.update(choices=[], value=None), 0.0, 0.0, "", "", {}

    src = source_input.strip()
    try:
        progress(0.05, desc="Ingesting media & extracting 16kHz WAV...")
        ing = ingest_source(src)
        v_path, a_path, meta = ing["video_path"], ing["audio_path"], ing["metadata"]

        progress(0.25, desc="Computing chunked audio RMS excitement...")
        audio_sig = compute_audio_energy(a_path)

        progress(0.35, desc="Parsing chat log (if provided)...")
        chat_sig = None
        if chat_file is not None:
            cp = chat_file.name if hasattr(chat_file, "name") else str(chat_file)
            chat_sig = parse_chat_log(cp, duration=meta["duration"])

        progress(0.45, desc="Transcribing speech with faster-whisper (CPU int8)...")
        def on_trans_prog(pct: float, desc: str):
            progress(0.45 + pct * 0.40, desc=desc)

        try:
            trans_res = transcribe_audio(a_path, progress_cb=on_trans_prog)
        except Exception:
            trans_res = {"segments": [], "words": []}

        progress(0.90, desc="Ranking top non-overlapping highlight intervals...")
        cands = rank_highlights(meta["duration"], audio_sig, chat_sig, trans_res, prompt, duration_preset, top_k=6)
        if not cands:
            return "⚠️ No clear highlights found.", gr.update(choices=[], value=None), 0.0, 0.0, "", "", {}

        choices = [f"#{i+1}: {c['start']}s - {c['end']}s ({c['duration']}s) [{c['evidence_badge']}]" for i, c in enumerate(cands)]
        top = cands[0]
        state = {"video_path": v_path, "meta": meta, "transcript": trans_res, "candidates": cands}
        status = f"✅ Found {len(cands)} highlight clips from {Path(v_path).name} ({meta['duration']:.1f}s)! Switch to Tab 2 to preview & render."
        progress(1.0, desc="Done!")
        return status, gr.update(choices=choices, value=choices[0]), top["start"], top["end"], top["reason"], top.get("transcript_snippet", ""), state

    except Exception as exc:
        err_msg = f"❌ Error: {str(exc)}"
        gr.Warning(err_msg)
        return err_msg, gr.update(choices=[], value=None), 0.0, 0.0, "", "", {}


def on_candidate_select(selected_label: str, state: Dict[str, Any]) -> tuple[float, float, str, str]:
    """Update start/end sliders and reason when a candidate is chosen."""
    cands = state.get("candidates", [])
    if not selected_label or not cands:
        return 0.0, 0.0, "", ""
    idx = int(selected_label.split(":")[0].replace("#", "")) - 1
    if 0 <= idx < len(cands):
        c = cands[idx]
        return c["start"], c["end"], c["reason"], c.get("transcript_snippet", "")
    return 0.0, 0.0, "", ""


def on_render_selected(
    start_sec: float,
    end_sec: float,
    layout_name: str,
    corner_name: str,
    music_file: Optional[Any],
    music_vol: float,
    state: Dict[str, Any],
    progress: gr.Progress = gr.Progress(),
) -> tuple[str, Optional[str]]:
    """Render single clip using fast input seeking, background music mixing, and ASS subtitles."""
    v_path = state.get("video_path")
    if not v_path or not os.path.isfile(v_path):
        return "❌ Video file missing or not ingested yet.", None

    try:
        progress(0.3, desc="Rendering clip with FFmpeg fast seeking & ASS subtitles...")
        layout, corner = LAYOUT_MAP.get(layout_name, "gaming_split"), CORNER_MAP.get(corner_name, "bottom-left")
        stem = Path(v_path).stem
        out_file = EXPORTS_DIR / f"{stem}_{int(start_sec)}s_{int(end_sec)}s_{corner}_{layout}.mp4"
        m_path = music_file.name if hasattr(music_file, "name") else (str(music_file) if music_file else None)

        render_clip(
            video_path=v_path,
            start_sec=start_sec,
            end_sec=end_sec,
            output_mp4=str(out_file),
            layout=layout,
            corner=corner,
            words=state.get("transcript", {}).get("words", []),
            apply_loudnorm=True,
            music_path=m_path,
            music_volume=music_vol,
        )
        progress(1.0, desc="Render complete!")
        return f"🎉 Exported clip to: {out_file.name}", str(out_file)
    except Exception as exc:
        err = f"❌ Render failed: {str(exc)}"
        gr.Warning(err)
        return err, None


def on_batch_export(
    layout_name: str,
    corner_name: str,
    music_file: Optional[Any],
    music_vol: float,
    state: Dict[str, Any],
    progress: gr.Progress = gr.Progress(),
) -> tuple[str, Optional[str]]:
    """Batch export all ranked candidates."""
    cands, v_path = state.get("candidates", []), state.get("video_path")
    if not v_path or not cands:
        return "❌ No highlights to batch export.", None

    try:
        layout, corner = LAYOUT_MAP.get(layout_name, "gaming_split"), CORNER_MAP.get(corner_name, "bottom-left")
        words = state.get("transcript", {}).get("words", [])
        m_path = music_file.name if hasattr(music_file, "name") else (str(music_file) if music_file else None)
        last_rendered = None

        for i, c in enumerate(cands):
            progress((i + 1) / len(cands), desc=f"Rendering clip {i+1}/{len(cands)}...")
            stem = Path(v_path).stem
            out_f = EXPORTS_DIR / f"{stem}_clip{i+1}_{int(c['start'])}s_{int(c['end'])}s_{layout}.mp4"
            render_clip(
                v_path, c["start"], c["end"], str(out_f),
                layout=layout, corner=corner, words=words,
                apply_loudnorm=True, music_path=m_path, music_volume=music_vol
            )
            last_rendered = str(out_f)

        return f"🚀 Successfully batch exported {len(cands)} clips to ./exports/", last_rendered
    except Exception as exc:
        err = f"❌ Batch export failed: {str(exc)}"
        gr.Warning(err)
        return err, None


def create_app() -> gr.Blocks:
    """Build Gradio 6 compliant UI."""
    with gr.Blocks(title="GTA 6 Gaming Clipper") as demo:
        app_state = gr.State({})
        gr.Markdown("# 🎮 Same-Day Local GTA 6 Gaming Clipper\n*100% Local, CPU-first, fast seeking, 9:16 split-screen with animated ASS captions & music.*")

        with gr.Tab("1. Ingest & Highlight Discovery"):
            with gr.Row():
                with gr.Column(scale=3):
                    source_box = gr.Textbox(
                        label="Local Video Path or URL",
                        placeholder="e.g. C:\\Videos\\gta6_session.mp4 or https://youtube.com/watch?v=...",
                        info="Enter local path to avoid multi-GB browser upload copies.",
                    )
                    prompt_box = gr.Textbox(label="Highlight Prompt", value="GTA 6 funny fails, chases, crazy reactions, 30-45s")
                with gr.Column(scale=2):
                    chat_upload = gr.File(label="Optional Chat Log (.json / .txt)", file_types=[".json", ".txt"])
                    preset_drop = gr.Dropdown(label="Target Clip Duration", choices=["15s", "30s", "45s", "60s", "Auto"], value="30s")
            find_btn = gr.Button("🔍 Find Highlights", variant="primary", size="lg")
            status_box = gr.Textbox(label="Status", interactive=False)

        with gr.Tab("2. Review & Render"):
            with gr.Row():
                with gr.Column(scale=2):
                    cands_drop = gr.Dropdown(label="Ranked Highlights", choices=[], interactive=True)
                    reason_box = gr.Textbox(label="Evidence & Reason", interactive=False, lines=2)
                    transcript_box = gr.Textbox(label="Transcript Snippet", interactive=False, lines=2)
                    with gr.Row():
                        start_slider = gr.Slider(label="Start Time (s)", minimum=0, maximum=3600, step=0.1)
                        end_slider = gr.Slider(label="End Time (s)", minimum=0, maximum=3600, step=0.1)
                    with gr.Row():
                        layout_drop = gr.Dropdown(label="Layout", choices=list(LAYOUT_MAP.keys()), value="Gaming Split-Screen (9:16)")
                        corner_drop = gr.Dropdown(label="Facecam Corner", choices=list(CORNER_MAP.keys()), value="Bottom-Left")
                    with gr.Row():
                        music_upload = gr.File(label="Optional Background Music (.mp3 / .wav)", file_types=[".mp3", ".wav", ".m4a"])
                        music_vol = gr.Slider(label="Music Volume Ducking", minimum=0.05, maximum=1.0, value=0.25, step=0.05)
                    with gr.Row():
                        render_btn = gr.Button("🎬 Render Selected Clip", variant="primary")
                        batch_btn = gr.Button("⚡ Batch Export All Highlights", variant="secondary")
                    render_status = gr.Textbox(label="Export Status", interactive=False)
                with gr.Column(scale=2):
                    video_preview = gr.Video(label="Rendered / Exported Video", interactive=False)

        find_btn.click(
            fn=on_find_highlights,
            inputs=[source_box, chat_upload, prompt_box, preset_drop],
            outputs=[status_box, cands_drop, start_slider, end_slider, reason_box, transcript_box, app_state],
        )
        cands_drop.change(
            fn=on_candidate_select,
            inputs=[cands_drop, app_state],
            outputs=[start_slider, end_slider, reason_box, transcript_box],
        )
        render_btn.click(
            fn=on_render_selected,
            inputs=[start_slider, end_slider, layout_drop, corner_drop, music_upload, music_vol, app_state],
            outputs=[render_status, video_preview],
        )
        batch_btn.click(
            fn=on_batch_export,
            inputs=[layout_drop, corner_drop, music_upload, music_vol, app_state],
            outputs=[render_status, video_preview],
        )
    return demo


demo = create_app()

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, inbrowser=True)
