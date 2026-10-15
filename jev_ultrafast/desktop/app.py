"""DesktopApp: the desktop twin of Browser — observe / fresh / act / close.

One AX session per app. Element ids persist across observations for living
elements (mirroring the browser layer's in-page WeakMap) and are retired, never
reused, when an element dies. No mutation ever happens on a stale decision.
"""

import time

from . import tree
from .ax import VALUE, AXBackend, ElementGone

CHECKBOX_RADIO = {"checkbox", "radio"}


class StaleState(ValueError):
    """A decision no longer refers to the observed app state. Observe again."""


def _default_backend() -> AXBackend:
    from .ax import PyobjcBackend

    return PyobjcBackend()


class DesktopApp:
    def __init__(self, bundle_id: str, backend: AXBackend | None = None):
        self.bundle_id = bundle_id
        self.backend = backend if backend is not None else _default_backend()
        self._app = None
        self._ids: dict[str, dict] = {}  # action id -> {"ref", "guard"}
        self._next = 0

    def _attach(self):
        """Re-resolve the app on every observation: restarts and pid reuse stay safe."""
        app = self.backend.application(self.bundle_id)
        if app is None:
            raise StaleState(f"{self.bundle_id} is not running. Start it, then attach again.")
        self._app = app

    def observe(self) -> dict:
        self._attach()
        state = tree.walk(self.backend, self._app)
        self._reconcile_ids(state["actions"])
        state["actions"].append({"id": "wait", "kind": "wait", "label": "Wait for the app to update"})
        return state

    def _reconcile_ids(self, actions: list[dict]) -> None:
        """Keep an element's id stable while it lives; retire ids of dead elements.

        Matching is by full guard (attributes + path + position): a recreated
        control in the same slot keeps its id, so an id never silently starts
        pointing at a different control. Guards are not unique — two identical
        controls each get their own id — so matched ids are consumed once.
        """
        by_guard: dict[tuple, list[str]] = {}
        for action_id, entry in self._ids.items():
            by_guard.setdefault(entry["guard"], []).append(action_id)
        seen: set[str] = set()
        for action in actions:
            action_id = next((i for i in by_guard.get(action["guard"], []) if i not in seen), None)
            if action_id is None:
                self._next += 1
                action_id = f"e{self._next}"
            action["id"] = action_id
            self._ids[action_id] = {"ref": action["ref"], "guard": action["guard"]}
            seen.add(action_id)
        for action_id in list(self._ids):
            if action_id not in seen:
                del self._ids[action_id]

    def fresh(self, page: dict, action: dict | None = None) -> bool:
        if self._app is None:
            return False
        if action is None:
            return tree.marker_of(
                self.backend, self._app, tree.windows_of(self.backend, self._app),
                len(page["actions"]),
            ) == page["marker"]
        entry = self._ids.get(action["id"])
        if entry is None:
            return False
        try:
            return tree.read_guard(self.backend, entry["ref"], self._app) == entry["guard"]
        except ElementGone:
            return False

    def act(self, action: dict, page: dict, text: str | None = None) -> dict:
        kind = action["kind"]
        if kind != "wait" and not self.fresh(page, action):
            raise StaleState("App state changed since this decision. Observe again.")
        entry = None if kind == "wait" else self._ids[action["id"]]
        try:
            if kind == "wait":
                time.sleep(0.1)
            elif kind == "click":
                if not self._pressable(entry["ref"], action["role"]):
                    raise StaleState("Target is no longer pressable. Observe again.")
                if not self.backend.perform(entry["ref"], "AXPress"):
                    raise StaleState("The press was refused. Inspect and observe again.")
            elif kind == "fill":
                if not self.backend.set(entry["ref"], VALUE, text or ""):
                    raise StaleState("The field refused the write. Inspect and observe again.")
                if self.backend.copy(entry["ref"], VALUE) != (text or ""):
                    raise StaleState("The value did not stick. Inspect and observe again.")
            else:
                raise ValueError(f"Unsupported action kind: {kind}")
        except ElementGone:
            raise StaleState("The element disappeared mid-action. Observe again.")
        return {"executed": action["id"]}

    def _pressable(self, ref, role: str) -> bool:
        try:
            return "AXPress" in self.backend.action_names(ref) or role in CHECKBOX_RADIO
        except ElementGone:
            return False

    def close(self) -> None:
        self._app = None
        self._ids.clear()


__all__ = ["DesktopApp", "StaleState"]
