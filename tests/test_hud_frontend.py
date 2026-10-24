"""Contract tests: the Python backend and the web front-end must agree."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from arceus.hud import session as session_mod
from arceus.hud.protocol import EVENT_TYPES, MAX_ACTIVITY, MAX_MESSAGES, HudState
from tests.hud_helpers import Harness, make_wav

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "arceus" / "hud" / "web"
HTML = (WEB / "index.html").read_text(encoding="utf-8")
JS = (WEB / "hud.js").read_text(encoding="utf-8")
MODEL = (WEB / "hud-model.js").read_text(encoding="utf-8")
QT = (ROOT / "arceus" / "hud" / "qt_shell.py").read_text(encoding="utf-8")
NODE = shutil.which("node")


def test_every_element_id_used_by_the_script_exists_once_in_the_page():
    html_ids = re.findall(r'\bid="([^"]+)"', HTML)
    assert len(html_ids) == len(set(html_ids)), "duplicate ids in index.html"
    used = set(re.findall(r"\$\('([A-Za-z0-9_-]+)'\)", JS))
    assert used, "no element lookups found (regex out of date?)"
    assert used <= set(html_ids), f"script uses missing ids: {used - set(html_ids)}"


def test_front_end_handles_every_event_type_the_backend_can_send():
    handled = set(re.findall(r"case '([a-z]+)':", JS.split("function apply")[1].split("function onEventJson")[0]))
    assert set(EVENT_TYPES) <= handled


def test_constants_match_between_python_and_javascript():
    assert re.findall(r"var STATES = \[(.*?)\];", MODEL)[0].replace("'", "").replace(" ", "").split(",") == [s.value for s in HudState]
    assert f"MAX_MESSAGES = {MAX_MESSAGES}" in MODEL and f"MAX_ACTIVITY = {MAX_ACTIVITY}" in MODEL
    # the backend must announce generation with the exact text the model uses to time responses
    assert "GENERATING RESPONSE" in MODEL
    assert '"GENERATING RESPONSE"' in (ROOT / "arceus/hud/session.py").read_text(encoding="utf-8")


def test_every_bridge_call_in_the_script_is_a_slot_in_the_qt_shell():
    called = set(re.findall(r"bridge\.([A-Za-z]+)\(", JS)) - {"eventJson"}
    slots = set(re.findall(r"@Slot\([^)]*\)\s+def ([A-Za-z]+)\(", QT))
    assert called <= slots, f"JS calls bridge methods that Python does not expose: {called - slots}"
    assert "eventJson = Signal(str)" in QT


def _code_only(source: str) -> str:
    """Strip comments so the checks below look at executable code only."""
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", source)


def test_page_is_local_only_and_never_injects_html():
    code = _code_only(JS) + _code_only(MODEL)
    assert "innerHTML" not in code and "outerHTML" not in code and "insertAdjacentHTML" not in code
    assert "eval(" not in code and "new Function" not in code
    for name in ("index.html", "hud.css", "hud.js", "hud-model.js"):
        text = (WEB / name).read_text(encoding="utf-8")
        # the SVG namespace identifier is a name, not something the browser fetches
        text = text.replace("http://www.w3.org/2000/svg", "")
        assert not re.search(r"https?://", text), f"{name} references a remote URL"
    for ref in re.findall(r'(?:src|href)="([^"]+)"', HTML):
        assert ref.startswith("qrc:") or (WEB / ref).is_file(), ref


def test_qt_shell_blocks_navigation_and_popups():
    assert "def acceptNavigationRequest" in QT and "def createWindow" in QT
    assert "return None" in QT.split("def createWindow")[1][:200]
    assert "QTcpServer" not in QT and "http.server" not in QT and "socket" not in QT  # no network listener


def test_session_has_no_network_listener():
    src = (ROOT / "arceus/hud/session.py").read_text(encoding="utf-8")
    assert "socket" not in src and "http.server" not in src and "bind(" not in src


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_node_suite_for_the_front_end_passes():
    result = subprocess.run(
        [NODE, "--test", "tests/js/model.test.js", "tests/js/smoke.test.js"],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_real_backend_events_drive_the_real_front_end_model(tmp_path):
    script = [
        ("listening_started", {"duration": 5.0}), ("captured", {"wav_bytes": make_wav(8000)}),
        ("transcribing", {}), ("transcribed", {"text": "hello"}), ("thinking", {}),
        ("reply", {"text": "hi there"}), ("speaking_started", {}), ("speaking_finished", {}),
    ]
    h = Harness(voice_script=script)
    try:
        h.session.request_snapshot()
        h.session.submit_text("typed question"); assert h.idle()
        h.session.start_voice(); assert h.idle()
        h.session.request_snapshot()
        events = json.loads(json.dumps(h.events))          # exactly what crosses the bridge
    finally:
        h.close()
    path = tmp_path / "events.json"
    path.write_text(json.dumps(events), encoding="utf-8")
    out = subprocess.run([NODE, "tests/js/replay.js", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout)
    texts = [(m["role"], m["text"], m["source"]) for m in result["state"]["messages"]]
    assert texts[0] == ("user", "typed question", "text")
    assert ("user", "hello", "voice") in texts and ("assistant", "hi there", "voice") in texts
    assert result["view"]["state"] == "STANDBY"
    assert result["id"] == "ARCEUS CORE / ECHO TEST"
    assert result["state"]["devices"]["last_capture"]["peak_dbfs"] < 0
    assert result["state"]["lastResponseMs"] is not None       # response timing was measured
