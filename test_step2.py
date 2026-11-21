"""test_step2.py: Verification suite for Step 2 components.
Verifies ranker.py (signal blending, offline Ollama fallback, NMS) and
render.py (fast seeking, 9:16 gaming split-screen, corner selector, animated ASS, loudnorm).
"""

from __future__ import annotations
import os
from pathlib import Path
import subprocess
import pytest

from ingest import probe_media
from ranker import rank_highlights, check_ollama
from render import render_clip, generate_ass_subtitles


@pytest.fixture(scope="session")
def synth_10s_video(tmp_path_factory):
    """Create a 10-second synthetic 1280x720 test video with audio using FFmpeg."""
    out_dir = tmp_path_factory.mktemp("render_media")
    video_path = out_dir / "synth_10s.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi", "-i", "testsrc=duration=10:size=1280x720:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=800:duration=10",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        str(video_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0, f"FFmpeg creation failed: {res.stderr}"
    return str(video_path)


def test_step2_module_line_limits():
    """Verify both ranker.py and render.py are strictly under 250 lines."""
    for mod in ["ranker.py", "render.py"]:
        p = Path(mod)
        assert p.exists(), f"{mod} missing"
        lines = len(p.read_text(encoding="utf-8").splitlines())
        assert lines < 250, f"{mod} exceeds 250 lines: {lines} lines"


def test_ranker_offline_ollama_fallback():
    """Verify ranker runs without error when Ollama is offline or unavailable."""
    # check_ollama returns bool without throwing
    is_up = check_ollama(base_url="http://localhost:11434")
    assert isinstance(is_up, bool)

    audio_signals = [
        {"start": 0.0, "end": 3.0, "score": 0.2},
        {"start": 3.0, "end": 6.0, "score": 0.95},
        {"start": 6.0, "end": 9.0, "score": 0.3},
    ]
    transcript = {
        "segments": [
            {"start": 0.0, "end": 2.5, "text": "driving around quietly"},
            {"start": 3.0, "end": 5.8, "text": "WTF INSANE POLICE CHASE CRAZY FAIL"},
            {"start": 6.0, "end": 9.0, "text": "we survived that"},
        ]
    }
    highlights = rank_highlights(
        duration=10.0,
        audio_signals=audio_signals,
        chat_signals=None,
        transcript=transcript,
        user_prompt="GTA 6 crazy police chase fails",
        duration_preset="15s",
        top_k=2,
    )

    assert len(highlights) >= 1
    top = highlights[0]
    # The middle section with 0.95 audio and hype words should be the top highlight
    assert top["evidence_badge"] == "ai_estimated"
    assert top["score"] > 0.3
    assert top["duration"] >= 5.0


def test_ranker_chat_assisted():
    """Verify chat signals increase score and set chat_assisted evidence badge."""
    audio_signals = [{"start": 0.0, "end": 10.0, "score": 0.5}]
    chat_signals = [
        {"start": 0.0, "end": 4.0, "score": 0.1},
        {"start": 4.0, "end": 8.0, "score": 0.9},
    ]
    highlights = rank_highlights(
        duration=10.0,
        audio_signals=audio_signals,
        chat_signals=chat_signals,
        user_prompt="funny fails",
        duration_preset="15s",
        top_k=1,
    )
    assert len(highlights) == 1
    assert highlights[0]["evidence_badge"] == "chat_assisted"


def test_render_generate_ass_subtitles_offset(tmp_path):
    """Verify ASS subtitles offset timestamps to start at 00:00:00.00 and have karaoke styling."""
    sub_path = tmp_path / "test.ass"
    words = [
        {"start": 5.0, "end": 5.5, "word": "LOOK"},
        {"start": 5.6, "end": 6.0, "word": "AT"},
        {"start": 6.1, "end": 6.8, "word": "THAT"},
    ]
    # Clip starts at 5.0 and ends at 8.0
    generate_ass_subtitles(words, clip_start=5.0, clip_end=8.0, output_ass=str(sub_path))
    assert sub_path.exists()
    content = sub_path.read_text(encoding="utf-8")

    # Assert mobile-safe margin is set
    assert "MarginV, Encoding" in content
    assert ",250,1" in content
    # Assert timestamps are offset to 00:00:00.00
    assert "Dialogue: 0,0:00:00.00" in content
    # Assert yellow active-word highlight
    assert r"{\c&H00FFFF&\b1}" in content


def test_render_gaming_split_with_corner_selector(synth_10s_video, tmp_path):
    """Test 9:16 Gaming Split-Screen render with corner selector and fast input seeking."""
    out_mp4 = tmp_path / "gaming_split_top_right.mp4"
    words = [
        {"start": 2.2, "end": 2.8, "word": "INSANE"},
        {"start": 2.9, "end": 3.5, "word": "DRIFT"},
    ]
    res_path = render_clip(
        video_path=synth_10s_video,
        start_sec=2.0,
        end_sec=6.0,
        output_mp4=str(out_mp4),
        layout="gaming_split",
        corner="top-right",
        words=words,
        apply_loudnorm=True,
    )
    assert os.path.exists(res_path)

    # Probe rendered clip
    meta = probe_media(res_path)
    assert meta["width"] == 1080
    assert meta["height"] == 1920
    # Duration should be ~4 seconds
    assert 3.5 <= meta["duration"] <= 4.5
    assert meta["has_audio"] is True


def test_render_full_9_16(synth_10s_video, tmp_path):
    """Test Full 9:16 center crop layout."""
    out_mp4 = tmp_path / "full_9_16.mp4"
    res_path = render_clip(
        video_path=synth_10s_video,
        start_sec=1.0,
        end_sec=4.0,
        output_mp4=str(out_mp4),
        layout="full_9_16",
        apply_loudnorm=False,
    )
    assert os.path.exists(res_path)
    meta = probe_media(res_path)
    assert meta["width"] == 1080
    assert meta["height"] == 1920
