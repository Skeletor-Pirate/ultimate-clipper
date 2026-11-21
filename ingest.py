"""ingest.py: Video and audio ingestion pipeline for local clipper.
Handles local files and yt-dlp URLs, probing media info and extracting 16kHz mono WAV.
"""

from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Dict, Optional


def probe_media(video_path: str) -> Dict[str, Any]:
    """Inspect video using ffprobe and return duration, resolution, fps, and audio status."""
    path = Path(video_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,r_frame_rate",
        "-of",
        "json",
        str(path),
    ]

    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()}")

    data = json.loads(result.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(fmt.get("duration", 0.0))
    width, height, fps = 1920, 1080, 30.0
    has_audio = False

    for stream in streams:
        ctype = stream.get("codec_type")
        if ctype == "video":
            width = int(stream.get("width", width))
            height = int(stream.get("height", height))
            r_fps = stream.get("r_frame_rate", "30/1")
            try:
                if "/" in r_fps:
                    num, den = map(float, r_fps.split("/"))
                    fps = num / den if den != 0 else 30.0
                else:
                    fps = float(r_fps)
            except Exception:
                fps = 30.0
        elif ctype == "audio":
            has_audio = True

    return {
        "path": str(path),
        "duration": duration,
        "width": width,
        "height": height,
        "fps": fps,
        "has_audio": has_audio,
    }


def download_video(url: str, output_dir: str = "cache/downloads") -> str:
    """Download best video+audio mp4 using yt-dlp, handling generic streams and live check."""
    out_dir = Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import yt_dlp
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed. Install it with pip install yt-dlp") from exc

    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True}) as check_ydl:
        info = check_ydl.extract_info(url, download=False)
        if info.get("is_live") or info.get("live_status") == "is_live":
            title = info.get("title", "Livestream")
            raise ValueError(
                f"'{title}' is an active, ongoing live stream with no fixed end. "
                "Please provide a completed VOD, recorded video, or local video path."
            )

    ydl_opts = {
        "outtmpl": str(out_dir / "%(id)s_%(title).50s.%(ext)s"),
        "format": "bestvideo*+bestaudio/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        base, _ = os.path.splitext(filename)
        expected_mp4 = f"{base}.mp4"
        if os.path.exists(expected_mp4):
            return str(Path(expected_mp4).resolve())
        return str(Path(filename).resolve())


def extract_audio(video_path: str, output_wav: Optional[str] = None) -> str:
    """Extract 16kHz 16-bit mono PCM WAV for fast speech and RMS processing."""
    in_path = Path(video_path).resolve()
    if not in_path.is_file():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if output_wav is None:
        out_dir = in_path.parent / "audio"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_wav = out_dir / f"{in_path.stem}_16k.wav"
    else:
        out_wav = Path(output_wav).resolve()
        out_wav.parent.mkdir(parents=True, exist_ok=True)

    # Re-use existing WAV cache if valid
    if out_wav.is_file() and out_wav.stat().st_size > 4096:
        return str(out_wav)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(in_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(out_wav),
    ]

    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Audio extraction failed: {res.stderr.strip()}")

    return str(out_wav)


def ingest_source(source: str, cache_dir: str = "cache") -> Dict[str, Any]:
    """High-level ingestion handler for local path or web URL."""
    cache_path = Path(cache_dir).resolve()
    cache_path.mkdir(parents=True, exist_ok=True)

    if source.startswith(("http://", "https://")):
        video_path = download_video(source, str(cache_path / "downloads"))
    else:
        video_path = str(Path(source).resolve())

    meta = probe_media(video_path)
    audio_path = extract_audio(video_path, str(cache_path / "audio" / f"{Path(video_path).stem}_16k.wav"))

    return {
        "video_path": video_path,
        "audio_path": audio_path,
        "metadata": meta,
    }
