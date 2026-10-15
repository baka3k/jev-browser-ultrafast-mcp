"""Offline contracts for desktop action execution and freshness guards. No macOS required."""

import pytest

from jev_ultrafast.desktop import DesktopApp, StaleState
from tests.test_desktop import FakeElement, by_label, make_app


def app_with_actions(**kwargs):
    backend = make_app(**kwargs)
    app = DesktopApp(backend.bundle, backend=backend)
    return app, backend


def test_act_returns_executed_id_and_performs_press():
    app, backend = app_with_actions(buttons=1)
    page = app.observe()
    action = by_label(page, "Button 0")
    assert app.act(action, page) == {"executed": action["id"]}
    assert ("perform", "AXPress") in backend.mutations
    app.close()


def test_stale_decision_never_reaches_the_backend():
    app, backend = app_with_actions(buttons=1)
    page = app.observe()
    backend.app.windows[0].children[0].title = "Renamed"
    with pytest.raises(StaleState):
        app.act(by_label(page, "Button 0"), page)
    assert backend.mutations == []  # the guard fired before any mutation
    app.close()


@pytest.mark.parametrize("mutation", ["dead", "relabel", "move", "disable", "unpress"])
def test_stale_variants_are_all_caught(mutation):
    app, backend = app_with_actions(buttons=1)
    page = app.observe()
    element = backend.app.windows[0].children[0]
    if mutation == "dead":
        element.dead = True
    elif mutation == "relabel":
        element.title = "Renamed"
    elif mutation == "move":
        element.position = (99, 99)
    elif mutation == "disable":
        element.enabled = False
    elif mutation == "unpress":
        element.press = []
    with pytest.raises(StaleState):
        app.act(by_label(page, "Button 0"), page)
    app.close()


def test_focus_flips_do_not_spuriously_stale_actions():
    app, backend = app_with_actions(buttons=1)
    page = app.observe()
    backend.app.focused = backend.app.windows[0].children[0]  # focus churn between observe and act
    assert app.act(by_label(page, "Button 0"), page)["executed"]
    app.close()


def test_marker_change_stales_done_style_checks_only():
    app, backend = app_with_actions(buttons=1)
    page = app.observe()
    backend.app.focused = backend.app.windows[0].children[0]
    assert app.fresh(page) is False  # DONE/BLOCKED-style: marker decides
    app.close()


def test_click_refused_when_press_disappears_after_observe():
    app, backend = app_with_actions(buttons=1)
    page = app.observe()
    backend.app.windows[0].children[0].press = []
    with pytest.raises(StaleState, match="pressable"):
        app.act(by_label(page, "Button 0"), page)
    assert not any(kind == "perform" for kind, _ in backend.mutations)
    app.close()


def test_fill_verifies_the_value_sticks():
    app, backend = app_with_actions(fields=1)
    page = app.observe()
    action = by_label(page, "Field 0")
    assert app.act(action, page, text="hello")["executed"]
    assert backend.app.windows[0].children[0].value == "hello"
    app.close()


def test_fill_detects_a_lying_field():
    app, backend = app_with_actions(fields=1)
    page = app.observe()
    backend.app.windows[0].children[0].transform = lambda value: value.upper()
    with pytest.raises(StaleState, match="did not stick"):
        app.act(by_label(page, "Field 0"), page, text="hello")
    app.close()


def test_fill_refusal_is_not_retried():
    app, backend = app_with_actions(fields=1)
    page = app.observe()
    backend.app.windows[0].children[0].writable.clear()  # field stops accepting writes
    with pytest.raises(StaleState):
        app.act(by_label(page, "Field 0"), page, text="hello")
    assert len([m for m in backend.mutations if m[0] == "set"]) == 1  # one attempt, never retried
    app.close()


def test_dead_element_at_act_time_maps_to_stalestate():
    app, backend = app_with_actions(buttons=1)
    page = app.observe()
    backend.app.windows[0].children[0].dead = True
    with pytest.raises(StaleState):
        app.act(by_label(page, "Button 0"), page)
    app.close()


def test_wait_needs_no_guard():
    app, backend = app_with_actions(buttons=1)
    page = app.observe()
    backend.app.focused = backend.app.windows[0].children[0]  # even a changed marker
    assert app.act({"id": "wait", "kind": "wait", "label": "Wait"}, page)["executed"] == "wait"
    app.close()


def test_disabled_controls_are_never_offered():
    app, backend = app_with_actions(buttons=0)
    backend.app.windows[0].children.append(FakeElement("AXButton", title="Grayed", enabled=False))
    page = app.observe()
    assert "Grayed" not in [a["label"] for a in page["actions"]]
    app.close()


def test_unknown_action_id_is_stale():
    app, _ = app_with_actions(buttons=1)
    page = app.observe()
    with pytest.raises(StaleState):
        app.act({"id": "e999", "kind": "click", "label": "Ghost", "role": "button", "node": 999}, page)
    app.close()


def test_close_is_idempotent_and_observe_reattaches():
    app, backend = app_with_actions(buttons=1)
    app.observe()
    app.close()
    app.close()
    assert app.observe()["actions"]  # fresh attach after close
    app.close()
