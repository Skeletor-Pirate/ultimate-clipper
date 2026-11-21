"""signals.py: Multi-signal extractor for local gaming clipper.
Computes audio RMS excitement via chunked soundfile.blocks, parses chat logs
with hype-boost & spam filtering, and transcribes speech using faster-whisper.
"""

from __future__ import annotations
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
import soundfile as sf

HYPE_EMOTES = {
    "lul", "omegalul", "w", "pog", "poggers", "pogchamp", "clip it", "clip",
    "wtf", "no way", "lmao", "haha", "kekw", "sheesh", "holy", "crazy", "insane"
}
BOT_PREFIXES = ("!", "/", "$", ".bot", "http://", "https://", "twitch.tv/")


def compute_audio_energy(
    wav_path: str,
    window_sec: float = 3.0,
    hop_sec: float = 1.0,
) -> List[Dict[str, float]]:
    """Stream WAV in blocks via soundfile.blocks to keep RAM low even on 6+ hour VODs."""
    p = Path(wav_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Audio file not found: {wav_path}")

    results: List[Dict[str, float]] = []
    raw_rms: List[float] = []

    with sf.SoundFile(str(p)) as f:
        sr = f.samplerate
        win_samples = max(1, int(window_sec * sr))
        hop_samples = max(1, int(hop_sec * sr))

        buf = np.zeros(0, dtype=np.float32)
        curr_t = 0.0

        for block in f.blocks(blocksize=hop_samples, dtype="float32"):
            if block.ndim > 1:
                block = np.mean(block, axis=1)
            buf = np.concatenate([buf, block])

            while len(buf) >= win_samples:
                win = buf[:win_samples]
                rms = float(np.sqrt(np.mean(win ** 2) + 1e-12))
                raw_rms.append(rms)
                results.append({"start": round(curr_t, 2), "end": round(curr_t + window_sec, 2), "score": rms})
                buf = buf[hop_samples:]
                curr_t += hop_sec

    if not results:
        return []

    p10 = float(np.percentile(raw_rms, 10))
    p95 = float(np.percentile(raw_rms, 95))
    span = p95 - p10 if (p95 - p10) > 1e-6 else (max(raw_rms) - min(raw_rms) + 1e-6)

    for item in results:
        norm = (item["score"] - p10) / span
        item["score"] = float(np.clip(norm, 0.0, 1.0))

    return results


def _parse_time_str(ts_str: str) -> float:
    """Parse HH:MM:SS or MM:SS to seconds."""
    parts = ts_str.strip("[] ").split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    if len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return float(parts[0])


def parse_chat_messages(chat_path: str) -> List[Tuple[float, str, str]]:
    """Parse messages into (offset_sec, author, text) from Twitch, yt-dlp, or TXT."""
    p = Path(chat_path).resolve()
    if not p.is_file():
        raise FileNotFoundError(f"Chat file not found: {chat_path}")

    msgs: List[Tuple[float, str, str]] = []
    text = p.read_text(encoding="utf-8", errors="ignore")

    if text.strip().startswith("{") and '"comments"' in text:
        try:
            data = json.loads(text)
            for c in data.get("comments", []):
                sec = float(c.get("content_offset_seconds", 0.0))
                author = c.get("commenter", {}).get("display_name", "")
                body = c.get("message", {}).get("body", "")
                msgs.append((sec, author, body))
            return msgs
        except Exception:
            pass

    if text.strip().startswith("{"):
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                action = item.get("replayChatItemAction", {}).get("actions", [{}])[0]
                renderer = action.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer", {})
                if renderer:
                    t_str = renderer.get("time_in_seconds", 0.0)
                    author = renderer.get("authorName", {}).get("simpleText", "")
                    runs = renderer.get("message", {}).get("runs", [])
                    body = "".join(r.get("text", "") for r in runs)
                    msgs.append((float(t_str), author, body))
            except Exception:
                continue
        if msgs:
            return msgs

    pattern = re.compile(r"\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(?:([^:\n]+):)?\s*(.*)")
    for line in text.splitlines():
        line = line.strip()
        m = pattern.match(line)
        if m:
            t_sec = _parse_time_str(m.group(1))
            author = (m.group(2) or "").strip()
            body = (m.group(3) or "").strip()
            if body:
                msgs.append((t_sec, author, body))

    return msgs


def parse_chat_log(
    chat_path: str,
    duration: Optional[float] = None,
    bin_size: float = 3.0,
) -> List[Dict[str, float]]:
    """Parse chat, filtering bot/raid spam while boosting positive hype emotes."""
    raw_msgs = parse_chat_messages(chat_path)
    if not raw_msgs:
        return []

    cleaned: List[Tuple[float, str]] = []
    seen_recent: Dict[str, float] = {}

    for sec, author, body in raw_msgs:
        b_lower = body.lower().strip()
        if any(b_lower.startswith(bp) for bp in BOT_PREFIXES):
            continue

        key = f"{author}:{b_lower}"
        if key in seen_recent and (sec - seen_recent[key]) < 5.0:
            continue
        seen_recent[key] = sec

        cleaned.append((sec, b_lower))

    max_t = duration if duration is not None else (max(m[0] for m in cleaned) + bin_size if cleaned else 10.0)
    bins = int(math.ceil(max_t / bin_size))
    weights = np.zeros(bins, dtype=np.float32)

    for sec, b_lower in cleaned:
        b_idx = min(int(sec // bin_size), bins - 1)
        hype_boost = 1.0
        for emote in HYPE_EMOTES:
            if emote in b_lower:
                hype_boost += 1.5
        weights[b_idx] += hype_boost

    p90 = float(np.percentile(weights, 90)) if len(weights) > 0 else 1.0
    scale = p90 if p90 > 1e-4 else (float(np.max(weights)) if len(weights) > 0 else 1.0)
    scale = max(scale, 1e-6)

    output: List[Dict[str, float]] = []
    for i, w in enumerate(weights):
        norm = float(np.clip(w / scale, 0.0, 1.0))
        output.append({
            "start": round(i * bin_size, 2),
            "end": round(min((i + 1) * bin_size, max_t), 2),
            "score": norm,
        })
    return output


def transcribe_audio(
    wav_path: str,
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8",
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Dict[str, Any]:
    """Transcribe speech with word-level timestamps using faster-whisper + Silero VAD, with caching."""
    cache_json = Path(wav_path).with_suffix(".json")
    if cache_json.is_file():
        try:
            return json.loads(cache_json.read_text(encoding="utf-8"))
        except Exception:
            pass

    from faster_whisper import WhisperModel

    cpu_th = min(8, os.cpu_count() or 4)
    model = WhisperModel(model_size, device=device, compute_type=compute_type, cpu_threads=cpu_th)
    segments, info = model.transcribe(
        wav_path,
        beam_size=1,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400),
    )

    out_words: List[Dict[str, Any]] = []
    out_segs: List[Dict[str, Any]] = []
    total_sec = max(1.0, float(info.duration))

    for seg in segments:
        out_segs.append({"start": round(seg.start, 2), "end": round(seg.end, 2), "text": seg.text.strip()})
        if seg.words:
            for w in seg.words:
                out_words.append({
                    "start": round(w.start, 2),
                    "end": round(w.end, 2),
                    "word": w.word.strip(),
                    "prob": round(float(w.probability), 3),
                })
        if progress_cb:
            pct = min(1.0, seg.end / total_sec)
            progress_cb(pct, f"Transcribing speech: {int(pct*100)}% ({seg.end/60:.1f}m / {total_sec/60:.1f}m)")

    result = {
        "language": info.language,
        "duration": info.duration,
        "segments": out_segs,
        "words": out_words,
    }
    try:
        cache_json.write_text(json.dumps(result), encoding="utf-8")
    except Exception:
        pass
    return result
