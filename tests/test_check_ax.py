"""Offline contracts for the live check_ax helpers. No macOS required."""

import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


check_ax = load_script("check_ax")


def test_skip_chain_covers_every_unavailable_condition():
    ok = {"pyobjc_ok": True, "trusted": True, "chrome_running": True, "window_count": 1}
    cases = [
        ({"darwin": False, **ok}, "not macOS"),
        ({"darwin": True, "pyobjc_ok": False, **{k: v for k, v in ok.items() if k != "pyobjc_ok"}}, "pyobjc"),
        ({"darwin": True, "trusted": False, **{k: v for k, v in ok.items() if k != "trusted"}}, "Accessibility"),
        ({"darwin": True, "chrome_running": False, "window_count": None,
          **{k: v for k, v in ok.items() if k != "chrome_running"}}, "not running"),
        ({"darwin": True, "window_count": 0, **{k: v for k, v in ok.items() if k != "window_count"}},
         "without any window"),
    ]
    for kwargs, expected in cases:
        reason = check_ax.decide_skip(**kwargs)
        assert reason is not None and expected in reason
    assert check_ax.decide_skip(darwin=True, pyobjc_ok=True, trusted=True, chrome_running=True, window_count=2) is None


def test_verdict_parsing(tmp_path):
    doc = tmp_path / "spike-activation.md"
    assert check_ax.read_verdict(doc) is None
    doc.write_text("noise\nVERDICT=chrome-ui-only\nMASKING=unverified\n")
    assert check_ax.read_verdict(doc) == "chrome-ui-only"
    doc.write_text("VERDICT=enhanced-ui\n")
    assert check_ax.read_verdict(doc) == "enhanced-ui"
    assert check_ax.parse_verdict("no verdict here") is None


def test_table_assertions():
    good = {
        "windows": 1,
        "text": "hello",
        "actions": [
            {"id": "e1", "kind": "click", "label": "Chrome", "role": "menuitem", "value": ""},
            {"id": "e2", "kind": "click", "label": "File", "role": "menuitem", "value": ""},
            {"id": "e3", "kind": "click", "label": "Edit", "role": "menuitem", "value": ""},
            {"id": "e4", "kind": "click", "label": "View", "role": "menuitem", "value": ""},
            {"id": "e5", "kind": "click", "label": "History", "role": "menuitem", "value": ""},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    assert check_ax.check_table(good) == []

    bad = {
        "windows": 0,
        "text": "s3cret leak",
        "actions": [{"id": "e1", "kind": "click", "label": "x", "role": "button", "value": "s3cret"},
                    {"id": "e1", "kind": "click", "label": "y", "role": "button", "value": ""}],
    }
    failures = " ".join(check_ax.check_table(bad))
    assert "menuitem" in failures and "window" in failures and "secret" in failures and "duplicate" in failures


def test_the_committed_spike_doc_parses():
    doc = Path(__file__).resolve().parent.parent / "docs/plans/desktop-app-layer/spike-activation.md"
    assert check_ax.read_verdict(doc) == "chrome-ui-only"
