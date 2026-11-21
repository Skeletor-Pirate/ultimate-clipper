"""test_step3.py: Verification suite for Step 3 (app.py).
Verifies line constraints (<250 lines), clean Gradio 6 Blocks initialization,
and UI callback state handlers.
"""

from __future__ import annotations
from pathlib import Path
import pytest
import gradio as gr

import app
from app import create_app, on_candidate_select, on_find_highlights, on_render_selected


def test_app_line_limits():
    """Verify app.py is strictly under 250 lines."""
    p = Path("app.py")
    assert p.exists()
    lines = len(p.read_text(encoding="utf-8").splitlines())
    assert lines < 250, f"app.py has {lines} lines, exceeding 250 limit"


def test_app_create_blocks():
    """Verify create_app produces a valid Gradio Blocks instance."""
    demo = create_app()
    assert isinstance(demo, gr.Blocks)
    assert demo.title == "GTA 6 Gaming Clipper"


def test_app_candidate_select_callback():
    """Verify candidate selection logic updates sliders and text."""
    state = {
        "candidates": [
            {
                "start": 12.5,
                "end": 42.5,
                "reason": "Test audio spike",
                "transcript_snippet": "insane jump",
            }
        ]
    }
    start, end, reason, snippet = on_candidate_select("#1: 12.5s - 42.5s", state)
    assert start == 12.5
    assert end == 42.5
    assert "Test audio spike" in reason
    assert "insane jump" in snippet


def test_app_find_highlights_empty_input():
    """Verify empty input returns friendly error without crashing."""
    status, drop_up, s, e, r, snip, state = on_find_highlights("", None, "", "30s")
    assert "Please enter a local video file path or URL" in status
    assert drop_up.get("choices") == []
