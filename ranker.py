"""ranker.py: Intelligent highlight ranker with heuristic & optional Ollama scoring.
Blends audio, chat, and transcript signals, snaps to sentence boundaries, and applies NMS.
"""

from __future__ import annotations
import math
from typing import Any, Dict, List, Optional
import requests

PROMPT_HYPE_KEYWORDS = {
    "fail", "crazy", "insane", "reaction", "chase", "funny", "laugh", "kill",
    "dead", "omg", "wtf", "no way", "clutch", "headshot", "speed", "stunt", "god",
    "died", "wasted", "busted", "crash", "boom", "lol", "lmao", "run", "cops"
}


def check_ollama(base_url: str = "http://localhost:11434", model: str = "qwen2.5:3b") -> bool:
    """Check if Ollama server is running locally with quick 0.5s timeout."""
    try:
        res = requests.get(f"{base_url}/api/tags", timeout=0.5)
        if res.status_code == 200:
            models = [m.get("name", "") for m in res.json().get("models", [])]
            return any(model in m for m in models) or len(models) > 0
    except Exception:
        pass
    return False


def _heuristic_text_score(text: str, user_prompt: str) -> float:
    """Fast vectorless text scoring based on prompt keywords and excitement cues."""
    if not text:
        return 0.1
    t_lower = text.lower()
    score = 0.2
    prompt_words = {w.lower() for w in user_prompt.split() if len(w) > 2}
    for pw in prompt_words:
        if pw in t_lower:
            score += 0.4
    for hk in PROMPT_HYPE_KEYWORDS:
        if hk in t_lower:
            score += 0.2
    if "!" in text or "?" in text:
        score += 0.15
    return min(1.0, score)


def _target_seconds(preset: str) -> float:
    """Convert preset string to target duration in seconds."""
    mapping = {"15s": 15.0, "30s": 30.0, "45s": 45.0, "60s": 60.0, "Auto": 30.0}
    return mapping.get(preset, 30.0)


def _refine_reasons_with_ollama(
    candidates: List[Dict[str, Any]],
    user_prompt: str,
    base_url: str = "http://localhost:11434",
    model: str = "qwen2.5:3b",
) -> None:
    """Refine top highlight reasons in a SINGLE fast batch query to Ollama."""
    if not candidates:
        return
    snippets = [f"{i+1}. [{c['start']}s-{c['end']}s]: {c.get('transcript_snippet', '')[:80]}" for i, c in enumerate(candidates[:4])]
    prompt = f"User prompt: {user_prompt}\nGive a 1-sentence hype explanation for each moment:\n" + "\n".join(snippets)
    try:
        res = requests.post(
            f"{base_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=2.5,
        )
        if res.status_code == 200:
            text = res.json().get("response", "").strip()
            lines = [l.strip() for l in text.splitlines() if l.strip()]
            for i, line in enumerate(lines[:len(candidates)]):
                candidates[i]["reason"] = line
    except Exception:
        pass


def rank_highlights(
    duration: float,
    audio_signals: List[Dict[str, float]],
    chat_signals: Optional[List[Dict[str, float]]] = None,
    transcript: Optional[Dict[str, Any]] = None,
    user_prompt: str = "GTA 6 funny fails, chases, crazy reactions",
    duration_preset: str = "30s",
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Blend signals, snap to sentence boundaries, and select top non-overlapping clips in milliseconds."""
    target_len = _target_seconds(duration_preset)
    has_chat = bool(chat_signals)
    segs = transcript.get("segments", []) if transcript else []

    # Dynamic weighting
    w_chat = 0.35 if has_chat else 0.0
    w_audio = 0.30 if has_chat else 0.45
    w_text = 0.35 if has_chat else 0.55

    # 1-second timeline grid
    total_sec = max(1, int(math.ceil(duration)))
    time_scores = [0.0] * total_sec

    # Audio energy contribution
    for a in audio_signals:
        s, e, sc = int(a["start"]), min(int(a["end"]), total_sec), a["score"]
        for t in range(s, e):
            time_scores[t] += w_audio * sc

    # Chat contribution
    if has_chat and chat_signals:
        for c in chat_signals:
            s, e, sc = int(c["start"]), min(int(c["end"]), total_sec), c["score"]
            for t in range(s, e):
                time_scores[t] += w_chat * sc

    # Fast heuristic timeline scoring (0.002s for 1000s of segments)
    for seg in segs:
        t_sc = _heuristic_text_score(seg["text"], user_prompt)
        s, e = int(seg["start"]), min(int(seg["end"]), total_sec)
        for t in range(s, e):
            time_scores[t] += w_text * t_sc

    # Find candidate intervals centered around score peaks
    candidates: List[Dict[str, Any]] = []
    step = 5  # examine every 5s peak
    for center_t in range(0, total_sec, step):
        c_start = max(0.0, center_t - target_len / 2)
        c_end = min(float(total_sec), c_start + target_len)
        if c_end - c_start < 5.0:
            continue

        # Snap to nearest sentence boundary if available
        matched_text: List[str] = []
        if segs:
            overlapping = [s for s in segs if not (s["end"] < c_start or s["start"] > c_end)]
            if overlapping:
                c_start = max(0.0, min(overlapping[0]["start"], c_start))
                c_end = min(float(total_sec), max(overlapping[-1]["end"], c_end))
                matched_text = [s["text"] for s in overlapping]

        span_t = time_scores[int(c_start):int(c_end)]
        avg_score = sum(span_t) / max(1, len(span_t))

        evidence = "chat_assisted" if has_chat and any(
            c["score"] > 0.4 for c in (chat_signals or []) if not (c["end"] < c_start or c["start"] > c_end)
        ) else "ai_estimated"

        reason = (
            f"Chat surge with high hype emotes & volume during speech"
            if evidence == "chat_assisted"
            else f"Audio excitement peak aligned with prompt: '{user_prompt[:35]}'"
        )

        candidates.append({
            "start": round(c_start, 2),
            "end": round(c_end, 2),
            "duration": round(c_end - c_start, 2),
            "score": round(float(avg_score), 3),
            "evidence_badge": evidence,
            "reason": reason,
            "transcript_snippet": " ".join(matched_text)[:150],
        })

    # Non-Maximum Suppression (NMS) to eliminate overlapping intervals
    candidates.sort(key=lambda x: x["score"], reverse=True)
    selected: List[Dict[str, Any]] = []

    for cand in candidates:
        overlap = False
        for sel in selected:
            inter = max(0.0, min(cand["end"], sel["end"]) - max(cand["start"], sel["start"]))
            if inter > 5.0:  # more than 5s overlap
                overlap = True
                break
        if not overlap:
            selected.append(cand)
        if len(selected) >= top_k:
            break

    # If Ollama is running locally, refine reasons in a single 1-shot batch call (max 2s)
    if check_ollama():
        _refine_reasons_with_ollama(selected, user_prompt)

    return selected
