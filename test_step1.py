"""test_step1.py: Verification suite for Step 1 components.
Verifies requirements.txt (av<16), module line constraints (<250 lines),
ingest.py (ffprobe & audio extraction), and signals.py (audio RMS & chat parsing).
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import tempfile
import pytest
import soundfile as sf
import numpy as np

from ingest import probe_media, extract_audio
from signals import compute_audio_energy, parse_chat_log, parse_chat_messages


@pytest.fixture(scope="session")
def synthetic_video(tmp_path_factory):
    """Generate a clean 3-second synthetic video with sine wave audio using ffmpeg."""
    out_dir = tmp_path_factory.mktemp("media")
    video_path = out_dir / "test_synth.mp4"
    cmd = [
        "ffmpeg",
        "-y",
        "-f", "lavfi", "-i", "testsrc=duration=3:size=640x360:rate=30",
        "-f", "lavfi", "-i", "sine=frequency=1000:duration=3",
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        str(video_path),
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert res.returncode == 0, f"FFmpeg failed to create test video: {res.stderr}"
    assert video_path.is_file()
    return str(video_path)


def test_requirements_pin():
    """Verify av<16 is explicitly pinned in requirements.txt."""
    req_file = Path("requirements.txt")
    assert req_file.exists(), "requirements.txt does not exist"
    content = req_file.read_text()
    assert "av<16" in content, "av<16 constraint missing from requirements.txt"
    assert "faster-whisper" in content


def test_module_line_limits():
    """Verify all Step 1 modules are strictly under 250 lines."""
    for mod in ["ingest.py", "signals.py"]:
        p = Path(mod)
        assert p.exists(), f"{mod} missing"
        lines = len(p.read_text(encoding="utf-8").splitlines())
        assert lines < 250, f"{mod} exceeds 250 lines: {lines} lines"


def test_ingest_probe_media(synthetic_video):
    """Test ffprobe probing metadata extraction."""
    meta = probe_media(synthetic_video)
    assert meta["duration"] >= 2.9
    assert meta["width"] == 640
    assert meta["height"] == 360
    assert meta["fps"] == 30.0
    assert meta["has_audio"] is True


def test_ingest_extract_audio(synthetic_video, tmp_path):
    """Test 16kHz mono WAV extraction."""
    target_wav = str(tmp_path / "extracted_16k.wav")
    out_wav = extract_audio(synthetic_video, target_wav)
    assert os.path.exists(out_wav)

    # Verify audio properties using soundfile
    with sf.SoundFile(out_wav) as f:
        assert f.samplerate == 16000
        assert f.channels == 1
        assert f.frames > 0


def test_signals_chunked_audio_energy(tmp_path):
    """Test RMS energy streaming in blocks with silence and tone."""
    sr = 16000
    # 2s silence followed by 2s loud tone
    silence = np.zeros(sr * 2, dtype=np.float32)
    tone = np.sin(2 * np.pi * 440 * np.linspace(0, 2, sr * 2)).astype(np.float32) * 0.9
    samples = np.concatenate([silence, tone])

    wav_path = tmp_path / "energy_test.wav"
    sf.write(str(wav_path), samples, sr)

    windows = compute_audio_energy(str(wav_path), window_sec=2.0, hop_sec=1.0)
    assert len(windows) >= 2
    # The later window containing the tone should have higher score than initial silence
    assert windows[-1]["score"] >= windows[0]["score"]
    for w in windows:
        assert 0.0 <= w["score"] <= 1.0


def test_signals_chat_parser_hype_boost_and_spam_filter(tmp_path):
    """Test chat parser: boosts 'W', 'POG', 'CLIP IT', filters bots and repeated spam."""
    chat_file = tmp_path / "chat_test.txt"
    chat_text = """
    [00:00:01] user1: Hello stream
    [00:00:02] Nightbot: !giveaway enter now http://spam.xyz
    [00:00:05] user2: WTF NO WAY THAT WAS INSANE
    [00:00:06] user3: POG POG W CLIP IT
    [00:00:07] spambot: buy followers now http://badsite.com
    [00:00:07] spambot: buy followers now http://badsite.com
    [00:00:08] spambot: buy followers now http://badsite.com
    [00:00:15] user4: ok moving on
    """
    chat_file.write_text(chat_text, encoding="utf-8")

    # 1. Test message extraction
    raw_msgs = parse_chat_messages(str(chat_file))
    assert len(raw_msgs) >= 6

    # 2. Test parsed score windows
    scores = parse_chat_log(str(chat_file), duration=20.0, bin_size=5.0)
    assert len(scores) >= 3

    # Window 1 (0-5s) has neutral + hype start, Window 2 (5-10s) has intense hype (WTF, POG, W, CLIP IT)
    # Window 2 should score highest
    w2 = [w for w in scores if w["start"] == 5.0][0]
    w3 = [w for w in scores if w["start"] == 15.0][0]
    assert w2["score"] > w3["score"], "Hype window should score higher than calm window"


def test_signals_chat_twitch_json(tmp_path):
    """Test TwitchDownloader JSON format support."""
    json_file = tmp_path / "twitch_chat.json"
    data = {
        "comments": [
            {
                "content_offset_seconds": 2.5,
                "commenter": {"display_name": "gamer1"},
                "message": {"body": "OMEGALUL LUL that fail"}
            },
            {
                "content_offset_seconds": 3.0,
                "commenter": {"display_name": "gamer2"},
                "message": {"body": "W reaction"}
            }
        ]
    }
    json_file.write_text(json.dumps(data), encoding="utf-8")
    scores = parse_chat_log(str(json_file), duration=10.0, bin_size=5.0)
    assert len(scores) >= 2
    assert scores[0]["score"] > 0.0
