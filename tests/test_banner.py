import pytest
import re

from arke.ui import banner


ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)

@pytest.mark.parametrize("mode,width,no_color", [
    ("FULL", 100, False),
    ("COMPACT", 40, False),
    ("FULL", 100, True),
    ("COMPACT", 40, True),
])
def test_generate_banner_snapshot(mode, width, no_color, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1" if no_color else "0")
    lines = banner.generate_banner(mode=mode, width=width)
    assert isinstance(lines, list)
    assert all(isinstance(line, str) for line in lines)
    for line in lines:
        visible = strip_ansi(line)
        if visible:
            assert len(visible) <= width
    assert any("/ask" in strip_ansi(line) for line in lines)

def test_statelessness(monkeypatch):
    out1 = banner.generate_banner(mode="FULL", width=100)
    out2 = banner.generate_banner(mode="FULL", width=100)
    assert out1 == out2

@pytest.mark.parametrize("mode", ["FULL", "COMPACT"])
def test_banner_no_color_env(mode, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    lines = banner.generate_banner(mode=mode, width=60)
    assert all("\033" not in l for l in lines)

def test_banner_width_detection(monkeypatch):
    monkeypatch.delenv("COLUMNS", raising=False)
    lines = banner.generate_banner(mode="FULL", width=None)
    assert isinstance(lines, list)
    assert lines
