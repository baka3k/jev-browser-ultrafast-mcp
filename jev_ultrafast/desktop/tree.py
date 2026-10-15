"""Pure AX-tree walker: backend + app element -> jev element table. No pyobjc imports.

Everything here is dict-in/dict-out and fully testable with a fake backend. Traversal
is bounded by node/depth budgets (a closed Chrome menu tree alone holds thousands of
nodes) and output is bounded separately (250 actions, 6000-char text preview).
"""

import hashlib
import json

from .ax import (
    CHILDREN,
    DESCRIPTION,
    ENABLED,
    HELP,
    MENU_BAR,
    PARENT,
    POSITION,
    ROLE,
    SIZE,
    TITLE,
    VALUE,
    WINDOWS,
)

MAX_ACTIONS = 250
MAX_NODES = 3000
MAX_DEPTH = 25
MAX_TEXT = 6000
MAX_MENU_CHILDREN = 40

ROLE_MAP = {
    "AXButton": "button",
    "AXCheckBox": "checkbox",
    "AXRadioButton": "radio",
    "AXPopUpButton": "combobox",
    "AXComboBox": "combobox",
    "AXTextField": "textbox",
    "AXTextArea": "textbox",
    "AXSearchField": "searchbox",
    "AXMenuBarItem": "menuitem",
    "AXMenuItem": "menuitem",
    "AXTabGroup": "tab",
}
EDITABLE_ROLES = {"textbox", "searchbox", "combobox"}
PRESSABLE_FALLBACK = {"checkbox", "radio"}  # AX checkboxes/radios support AXPress universally
SECURE_ROLE = "AXSecureTextField"
MENU_ROLES = {"AXMenu"}
WINDOW_ROLE = "AXWindow"


class _Budget:
    """Shared traversal budget: a hard stop, not just an output cap."""

    def __init__(self):
        self.nodes = 0
        self.exhausted = False

    def take(self) -> bool:
        if self.nodes >= MAX_NODES:
            self.exhausted = True
            return False
        self.nodes += 1
        return True


def role_of(raw_role: str | None) -> str | None:
    return ROLE_MAP.get(raw_role or "")


def label_of(backend, element) -> str:
    for attribute in (TITLE, DESCRIPTION, HELP):
        value = backend.copy(element, attribute)
        if value:
            return str(value)
    return ""


def path_of(backend, element, app) -> tuple:
    """Identity anchor: (role, title) pairs from the app down to this element."""
    steps = []
    current = element
    seen = 0
    while current is not None and current is not app and seen <= MAX_DEPTH:
        steps.append((backend.copy(current, ROLE), backend.copy(current, TITLE)))
        current = backend.copy(current, PARENT)
        seen += 1
    return tuple(reversed(steps))


def read_guard(backend, element, app) -> tuple | None:
    """The full freshness guard: attributes + identity anchor (path + position)."""
    mapped = role_of(backend.copy(element, ROLE))
    if mapped is None:
        return None
    position = backend.copy(element, POSITION)
    size = backend.copy(element, SIZE)
    return (
        mapped,
        label_of(backend, element),
        backend.copy(element, ENABLED) is not False,
        backend.copy(element, VALUE) if mapped in EDITABLE_ROLES else None,
        path_of(backend, element, app),
        (position, size) if position is not None and size is not None else None,
    )


def windows_of(backend, app) -> list:
    """Real windows only: windowless apps list the application element in AXWindows."""
    return [
        window for window in backend.copy(app, WINDOWS) or []
        if backend.copy(window, ROLE) == WINDOW_ROLE
    ]


def within(backend, needle, ancestor, app) -> bool:
    """Whether `needle` lives inside `ancestor`'s subtree (identity-based)."""
    current = needle
    while current is not None:
        if backend.same(current, ancestor):
            return True
        if backend.same(current, app):
            return False
        current = backend.copy(current, PARENT)
    return False


def walk(backend, app) -> dict:
    """One atomic observation of the app: element table, marker, guards, caps."""
    actions: list[dict] = []
    texts: list[str] = []
    budget = _Budget()
    omitted = 0

    def add_text(value) -> None:
        if isinstance(value, str) and value and len("\n".join(texts)) < MAX_TEXT:
            texts.append(value)

    def emit_action(element, mapped) -> None:
        if len(actions) >= MAX_ACTIONS:
            return
        if backend.copy(element, ENABLED) is False:
            return  # disabled controls are not offered, like the browser snapshot
        if mapped in EDITABLE_ROLES and backend.is_settable(element, VALUE):
            kind = "fill"  # a writable probe: readable-but-readonly fields stay out
        elif "AXPress" in backend.action_names(element) or mapped in PRESSABLE_FALLBACK:
            kind = "click"
        else:
            return
        guard = read_guard(backend, element, app)
        if guard is None:
            return
        value = backend.copy(element, VALUE) if kind == "fill" else None
        actions.append({
            "kind": kind,
            "label": label_of(backend, element) or mapped,
            "role": mapped,
            "value": str(value) if value is not None else "",
            "node": len(actions),
            "ref": element,
            "guard": guard,
        })

    def visit(element, depth: int, in_menu: bool, focused) -> None:
        nonlocal omitted
        if not budget.take() or depth > MAX_DEPTH:
            return
        raw_role = backend.copy(element, ROLE)
        if raw_role == SECURE_ROLE:
            return  # never enumerate secure fields, like the browser snapshot
        mapped = role_of(raw_role)
        title = backend.copy(element, TITLE)
        add_text(title)
        if mapped is not None:
            add_text(backend.copy(element, VALUE))
            emit_action(element, mapped)
        if raw_role in MENU_ROLES and not in_menu:
            # A menu's items are only visible while it is open; the open indicator is
            # the app's focused element living inside that menu (post-press state).
            if focused is None or not within(backend, focused, element, app):
                return
        children = backend.copy(element, CHILDREN) or []
        if raw_role in MENU_ROLES:
            children = children[:MAX_MENU_CHILDREN]
        for child in children:
            if len(actions) >= MAX_ACTIONS or budget.nodes >= MAX_NODES:
                omitted += 1  # counted once per skipped subtree, not per node
                continue
            visit(child, depth + 1, in_menu or raw_role in MENU_ROLES, focused)

    windows = windows_of(backend, app)
    focused = backend.copy(app, "AXFocusedUIElement")
    for window in windows:
        add_text(backend.copy(window, TITLE))
        visit(window, 0, False, focused)
    menubar = backend.copy(app, MENU_BAR)
    if menubar:
        visit(menubar, 0, False, focused)

    state = {
        "app": backend.copy(app, TITLE) or "",
        "title": backend.copy(windows[0], TITLE) if windows else backend.copy(app, TITLE) or "",
        "windows": len(windows),
        "text": "\n".join(texts)[:MAX_TEXT],
        "actions": actions,
        "marker": marker_of(backend, app, windows, len(actions)),
        "omitted_actions": omitted,
    }
    state["fingerprint"] = fingerprint(state)
    return state


def marker_of(backend, app, windows, action_count) -> list:
    """Cheap app-level state, validated only for DONE/BLOCKED-style decisions."""
    focused = backend.copy(app, "AXFocusedUIElement")
    focused_state = None
    menu_open = False
    if focused is not None:
        focused_value = backend.copy(focused, VALUE)
        focused_role = backend.copy(focused, ROLE)
        focused_state = (focused_role, backend.copy(focused, TITLE),
                         focused_value if isinstance(focused_value, str) else None)
        parent = backend.copy(focused, PARENT)
        parent_role = backend.copy(parent, ROLE) if parent is not None else None
        menu_open = focused_role in MENU_ROLES or parent_role in MENU_ROLES
    return [len(windows), [backend.copy(window, TITLE) for window in windows],
            action_count, focused_state, menu_open]


def fingerprint(state: dict) -> str:
    """sha256 over semantic content only — never over refs or screenshots."""
    semantic = {
        key: ([{k: v for k, v in item.items() if k != "ref"} for item in state[key]]
              if key == "actions" else state[key])
        for key in ("app", "title", "text", "actions", "marker")
    }
    return hashlib.sha256(json.dumps(semantic, sort_keys=True, default=str).encode()).hexdigest()
