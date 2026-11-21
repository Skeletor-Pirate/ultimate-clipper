"""render.py: Fast FFmpeg render engine for 9:16 gaming split-screen & vertical clips.
Inspired by viral gaming channels (@sky_aep77, @the360gamer_, @ai_game_zone).
Supports middle-split captions, emojis, sound tags, and background music integration.
"""

from __future__ import annotations
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List, Optional

EMOJI_MAP = {
    "breathe": "😮‍💨", "breathing": "😮‍💨", "pant": "💨", "gasp": "😱", "sigh": "😮‍💨",
    "laugh": "😂", "lol": "🤣", "lmao": "💀", "haha": "😂", "dead": "💀", "die": "💀",
    "kill": "☠️", "omg": "😱", "god": "😱", "holy": "😳", "shit": "💩", "wtf": "🤯",
    "what": "❓", "wow": "🤩", "bro": "🤝", "dude": "🗣️", "fire": "🔥", "crazy": "🤪",
    "insane": "🤯", "hype": "⚡", "win": "🏆", "w": "👑", "fast": "⚡", "car": "🏎️",
    "drive": "🚗", "crash": "💥", "hit": "💥", "police": "🚨", "cops": "🚓",
    "money": "💰", "cash": "💵", "no": "❌", "yes": "✅", "shoot": "🎯", "gun": "🔫",
    "gta": "🎮", "run": "🏃", "look": "👀", "see": "👀", "jump": "🦘"
}


def _format_ass_time(sec: float) -> str:
    """Format seconds into ASS timestamp H:MM:SS.cs."""
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    cs = min(99, int(round((sec - int(sec)) * 100)))
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _find_emoji(text: str) -> str:
    """Find matching emoji for word or text snippet."""
    clean = re.sub(r"[^\w\s]", "", text.lower())
    for word in clean.split():
        if word in EMOJI_MAP:
            return EMOJI_MAP[word]
    return "🔥" if any(k in clean for k in ["crazy", "insane", "cool"]) else ""


def generate_ass_subtitles(
    words: List[Dict[str, Any]],
    clip_start: float,
    clip_end: float,
    output_ass: str,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    margin_v: int = 250,
) -> str:
    """Create animated ASS captions with emojis and sound tags, placed in the middle or bottom."""
    out_path = Path(output_ass).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Segoe UI Emoji,62,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,4,0,2,40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    clip_words = [w for w in words if w.get("end", 0.0) >= clip_start and w.get("start", 0.0) <= clip_end]
    events: List[str] = []

    if clip_words and (clip_words[0]["start"] - clip_start) >= 1.5:
        t_s = _format_ass_time(0.0)
        t_e = _format_ass_time(clip_words[0]["start"] - clip_start)
        events.append(f"Dialogue: 0,{t_s},{t_e},Default,,0,0,0,,*HEAVY BREATHING* 😮‍💨")

    chunk_size = 3
    for i in range(0, len(clip_words), chunk_size):
        chunk = clip_words[i : i + chunk_size]
        chunk_text = " ".join(w["word"] for w in chunk)
        emoji = _find_emoji(chunk_text)

        sound_tag = ""
        low = chunk_text.lower()
        if any(b in low for b in ["breath", "pant", "sigh"]):
            sound_tag = "*HEAVY BREATHING* 😮‍💨 "
        elif any(l in low for l in ["laugh", "haha", "lol"]):
            sound_tag = "*LAUGHING* 😂 "
        elif "gasp" in low:
            sound_tag = "*GASP* 😱 "

        for active_idx, target_w in enumerate(chunk):
            rel_start = max(0.0, target_w["start"] - clip_start)
            rel_end = max(rel_start + 0.12, target_w["end"] - clip_start)
            t_start = _format_ass_time(rel_start)
            t_end = _format_ass_time(rel_end)

            styled_parts = []
            for j, w in enumerate(chunk):
                txt = w["word"].strip().upper()
                if j == active_idx:
                    styled_parts.append(r"{\c&H00FFFF&\b1}" + txt + r"{\b0\c&HFFFFFF&}")
                else:
                    styled_parts.append(txt)

            line_text = (sound_tag + " ".join(styled_parts) + (f" {emoji}" if emoji else "")).strip()
            events.append(f"Dialogue: 0,{t_start},{t_end},Default,,0,0,0,,{line_text}")

        next_w_start = clip_words[i + chunk_size]["start"] if (i + chunk_size) < len(clip_words) else clip_end
        gap = next_w_start - chunk[-1]["end"]
        if gap >= 1.4:
            g_s = _format_ass_time(max(0.0, chunk[-1]["end"] - clip_start))
            g_e = _format_ass_time(max(0.0, next_w_start - clip_start))
            events.append(f"Dialogue: 0,{g_s},{g_e},Default,,0,0,0,,*INTENSE MOMENT* ⚡ 😮‍💨")

    full_ass = header + "\n".join(events) + "\n"
    out_path.write_text(full_ass, encoding="utf-8")
    return str(out_path)


def _build_video_filter(layout: str, corner: str, ass_escaped: Optional[str]) -> str:
    """Build FFmpeg complex filtergraph with unzoomed ambient facecam and middle split line."""
    c = corner.lower()
    if "top-right" in c:
        cam_crop = "crop=w=iw*0.50:h=ih*0.50:x=iw*0.50:y=0"
    elif "top-center" in c:
        cam_crop = "crop=w=iw*0.52:h=ih*0.48:x=iw*0.24:y=0"
    elif "bottom-right" in c:
        cam_crop = "crop=w=iw*0.52:h=ih*0.48:x=iw*0.48:y=ih*0.52"
    elif "bottom-center" in c:
        cam_crop = "crop=w=iw*0.52:h=ih*0.48:x=iw*0.24:y=ih*0.52"
    elif "bottom-left" in c:
        cam_crop = "crop=w=iw*0.52:h=ih*0.48:x=0:y=ih*0.52"
    else:  # top-left
        cam_crop = "crop=w=iw*0.50:h=ih*0.50:x=0:y=0"

    game_crop = "crop=w=iw:h=ih*0.62:x=0:y=0" if "bottom" in c else "crop=w=iw:h=ih*0.65:x=0:y=ih*0.35"

    if layout == "gaming_split":
        vf = (
            f"[0:v]split=3[cam_bg][cam_fg][game_in];"
            f"[cam_bg]{cam_crop},scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960,boxblur=20:5[top_bg];"
            f"[cam_fg]{cam_crop},scale=1080:960:force_original_aspect_ratio=decrease[top_fg];"
            f"[top_bg][top_fg]overlay=(W-w)/2:(H-h)/2[top];"
            f"[game_in]{game_crop},scale=1080:960:force_original_aspect_ratio=increase,crop=1080:960[bottom];"
            f"[top][bottom]vstack=inputs=2,drawbox=x=0:y=958:w=1080:h=4:color=white@0.85:t=fill[v_base]"
        )
    elif layout == "blur_fit":
        vf = (
            "[0:v]split=2[bg_in][fg_in];"
            "[bg_in]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bg];"
            "[fg_in]scale=1080:608[fg];"
            "[bg][fg]overlay=0:(1920-608)/2[v_base]"
        )
    elif layout == "full_9_16":
        vf = "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920[v_base]"
    else:
        vf = "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080[v_base]"

    last_v = "[v_base]"
    if ass_escaped:
        vf += f";{last_v}ass='{ass_escaped}'[v_out]"
    else:
        vf += f";{last_v}copy[v_out]"
    return vf


def render_clip(
    video_path: str,
    start_sec: float,
    end_sec: float,
    output_mp4: str,
    layout: str = "gaming_split",
    corner: str = "top-left",
    words: Optional[List[Dict[str, Any]]] = None,
    apply_loudnorm: bool = True,
    caption_position: str = "middle",
    music_path: Optional[str] = None,
    music_volume: float = 0.25,
) -> str:
    """Render vertical clip with fast seeking, background music mixing, and middle-split captions."""
    in_p = Path(video_path).resolve()
    if not in_p.is_file():
        raise FileNotFoundError(f"Source video not found: {video_path}")

    out_p = Path(output_mp4).resolve()
    out_p.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.5, end_sec - start_sec)

    ass_escaped: Optional[str] = None
    if words:
        margin_v = 925 if (layout == "gaming_split" or caption_position == "middle") else 250
        ass_file = out_p.parent / f"{out_p.stem}_sub.ass"
        generate_ass_subtitles(words, start_sec, end_sec, str(ass_file), margin_v=margin_v)
        ass_escaped = ass_file.as_posix().replace(":", r"\:").replace("'", r"\'")

    v_filter = _build_video_filter(layout, corner, ass_escaped)
    has_music = bool(music_path and os.path.isfile(music_path))

    cmd = ["ffmpeg", "-y", "-ss", f"{start_sec:.3f}", "-t", f"{duration:.3f}", "-i", str(in_p)]
    if has_music:
        cmd += ["-stream_loop", "-1", "-i", str(Path(music_path).resolve())]
        ln = ",loudnorm=I=-16:TP=-1.5:LRA=11" if apply_loudnorm else ""
        af = f"{v_filter};[0:a]volume=1.0[va];[1:a]volume={music_volume:.2f}[ma];[va][ma]amix=inputs=2:duration=first:dropout_transition=2{ln}[a_out]"
        cmd += ["-filter_complex", af, "-map", "[v_out]", "-map", "[a_out]"]
    else:
        a_filter = "loudnorm=I=-16:TP=-1.5:LRA=11" if apply_loudnorm else "anull"
        cmd += ["-filter_complex", v_filter, "-map", "[v_out]", "-map", "0:a?", "-af", a_filter]

    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-b:a", "192k", str(out_p)]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed: {res.stderr.strip()[-500:]}")

    return str(out_p)
