"""Offline contracts for the jev-desktop MCP server. No macOS required, no paid APIs."""

import json

import pytest

from jev_ultrafast import desktop_mcp
from jev_ultrafast.desktop import DesktopApp
from tests.test_desktop import make_app


@pytest.fixture(autouse=True)
def clean_session():
    desktop_mcp._desktop = None
    yield
    desktop_mcp.close_app()


def patch_desktop(monkeypatch, **app_kwargs):
    backend = make_app(**app_kwargs)
    monkeypatch.setattr(desktop_mcp, "DesktopApp",
                        lambda bundle: DesktopApp(bundle, backend=backend))
    return backend


def test_attach_rejects_apps_outside_the_allowlist(monkeypatch):
    monkeypatch.delenv("JEV_DESKTOP_ALLOW", raising=False)
    result = json.loads(desktop_mcp.attach_app("com.apple.Terminal"))
    assert "JEV_DESKTOP_ALLOW" in result["error"]
    assert desktop_mcp._desktop is None


def test_allowlist_is_extensible_via_env(monkeypatch):
    monkeypatch.setenv("JEV_DESKTOP_ALLOW", "com.test.app, com.other")
    patch_desktop(monkeypatch, buttons=1)
    result = json.loads(desktop_mcp.attach_app("com.test.app"))
    assert result["status"] == "success"
    monkeypatch.setenv("JEV_DESKTOP_ALLOW", "com.other")
    result = json.loads(desktop_mcp.attach_app("com.test.app"))
    assert "allowlist" in result["error"]


def test_observe_without_attach_is_an_error():
    assert "desktop_attach" in json.loads(desktop_mcp.observe_state())["error"]


def test_observe_formats_the_element_table_without_leaking_refs(monkeypatch):
    monkeypatch.setenv("JEV_DESKTOP_ALLOW", "com.test.app")
    patch_desktop(monkeypatch, buttons=2, fields=1, menubar_items=["Edit"])
    json.loads(desktop_mcp.attach_app("com.test.app"))
    result = json.loads(desktop_mcp.observe_state())
    assert result["element_count"] >= 3
    for element in result["elements"]:
        assert set(element) == {"id", "kind", "label", "value", "role"}
    assert "ref" not in json.dumps(result)
    assert result["elements"][-1]["id"] == "wait"


def test_act_happy_path_reports_the_new_state(monkeypatch):
    monkeypatch.setenv("JEV_DESKTOP_ALLOW", "com.test.app")
    backend = patch_desktop(monkeypatch, buttons=1)
    json.loads(desktop_mcp.attach_app("com.test.app"))
    table = json.loads(desktop_mcp.observe_state())
    action_id = next(e["id"] for e in table["elements"] if e["label"] == "Button 0")
    result = json.loads(desktop_mcp.act_by_id(action_id))
    assert result["status"] == "success"
    assert ("perform", "AXPress") in backend.mutations


def test_act_on_a_stale_element_returns_an_actionable_error(monkeypatch):
    monkeypatch.setenv("JEV_DESKTOP_ALLOW", "com.test.app")
    backend = patch_desktop(monkeypatch, buttons=1)
    json.loads(desktop_mcp.attach_app("com.test.app"))
    backend.app.windows[0].children[0].title = "Renamed"
    result = json.loads(desktop_mcp.act_by_id("e1"))
    assert "Observe again" in result["error"]


def test_act_with_an_unknown_id_asks_for_a_fresh_observe(monkeypatch):
    monkeypatch.setenv("JEV_DESKTOP_ALLOW", "com.test.app")
    patch_desktop(monkeypatch, buttons=1)
    json.loads(desktop_mcp.attach_app("com.test.app"))
    assert "not found" in json.loads(desktop_mcp.act_by_id("e999"))["error"]


def test_a_dead_app_session_clears_and_asks_for_reattach(monkeypatch):
    monkeypatch.setenv("JEV_DESKTOP_ALLOW", "com.test.app")
    backend = patch_desktop(monkeypatch, buttons=1)
    json.loads(desktop_mcp.attach_app("com.test.app"))
    backend.app.dead = True  # the app quit: every AX touch on it now raises ElementGone
    result = json.loads(desktop_mcp.act_by_id("e1"))
    assert "desktop_attach" in result["error"]
    assert desktop_mcp._desktop is None


def test_fill_requires_text_and_reports_it(monkeypatch):
    monkeypatch.setenv("JEV_DESKTOP_ALLOW", "com.test.app")
    patch_desktop(monkeypatch, fields=1)
    json.loads(desktop_mcp.attach_app("com.test.app"))
    table = json.loads(desktop_mcp.observe_state())
    field_id = next(e["id"] for e in table["elements"] if e["kind"] == "fill")
    result = json.loads(desktop_mcp.act_by_id(field_id, text="typed"))
    assert result["status"] == "success"
    assert result["executed"]["text"] == "typed"


def test_close_is_idempotent():
    assert json.loads(desktop_mcp.close_app())["status"] == "success"
    assert json.loads(desktop_mcp.close_app())["status"] == "success"
