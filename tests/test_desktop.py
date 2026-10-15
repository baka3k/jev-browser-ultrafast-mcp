"""Offline contracts for the desktop AX layer. No paid APIs, no macOS required."""

import importlib
import sys

import pytest

from jev_ultrafast.agent import model
from jev_ultrafast.desktop import tree
from jev_ultrafast.desktop.ax import (
    ATTRIBUTE_UNSUPPORTED,
    INVALID_UI_ELEMENT,
    NO_VALUE,
    AXError,
    ElementGone,
    PyobjcBackend,
)


class FakeElement:
    def __init__(self, role, title="", value=None, children=(), press=("AXPress",),
                 writable=(), desc="", help_="", position=(0, 0), size=(10, 10), enabled=True):
        self.role, self.title, self.value = role, title, value
        self.desc, self.help = desc, help_
        self.children, self.press = list(children), list(press)
        self.writable = set(writable)
        self.position, self.size, self.enabled = position, size, enabled
        self.parent, self.windows, self.menubar, self.menus, self.focused = None, [], None, [], None
        self.dead = False
        self.transform = None  # optional value rewrite to simulate a lying field
        for child in children:
            child.parent = self


class FakeBackend:
    """In-memory AXBackend with a mutation log for guard-before-mutation proofs."""

    def __init__(self, app):
        self.app = app
        self.bundle = "com.test.app"
        self.copy_calls = 0
        self.mutations = []

    def application(self, bundle_id):
        return self.app if bundle_id == self.bundle else None

    def copy(self, element, attribute):
        if element.dead:
            raise ElementGone(f"copy {attribute}")
        self.copy_calls += 1
        return {
            tree.ROLE: element.role, tree.TITLE: element.title, tree.DESCRIPTION: element.desc,
            tree.HELP: element.help, tree.VALUE: element.value,
            tree.POSITION: element.position, tree.SIZE: element.size,
            tree.ENABLED: element.enabled, tree.CHILDREN: element.children,
            tree.PARENT: element.parent, tree.WINDOWS: element.windows,
            tree.MENU_BAR: element.menubar,
            "AXFocusedUIElement": element.focused,
        }.get(attribute)

    def set(self, element, attribute, value):
        self.mutations.append(("set", attribute))
        if element.dead:
            raise ElementGone(f"set {attribute}")
        if attribute not in element.writable or not element.enabled:
            return False
        element.value = element.transform(value) if element.transform else value
        return True

    def perform(self, element, action):
        self.mutations.append(("perform", action))
        if element.dead:
            raise ElementGone(f"perform {action}")
        return action in element.press

    def action_names(self, element):
        return [] if element.dead else list(element.press)

    def is_settable(self, element, attribute):
        return not element.dead and attribute in element.writable

    def same(self, a, b):
        return a is b


def make_app(buttons=0, fields=0, menubar_items=(), secure=False):
    content = [FakeElement("AXButton", title=f"Button {i}") for i in range(buttons)]
    content += [
        FakeElement("AXTextField", title=f"Field {i}", value="", writable={"AXValue"})
        for i in range(fields)
    ]
    if secure:
        content.append(FakeElement("AXSecureTextField", title="Password", value="s3cret"))
    window = FakeElement("AXWindow", title="Test Window", children=content)
    menubar = None
    if menubar_items:
        bar_items = [
            FakeElement("AXMenuBarItem", title=name, children=[FakeElement("AXMenu", title=name, children=[
                FakeElement("AXMenuItem", title=f"{name} item {i}") for i in range(3)
            ])])
            for name in menubar_items
        ]
        menubar = FakeElement("AXMenuBar", title="", children=bar_items)
    app = FakeElement("AXApplication", title="TestApp")
    app.windows = [window]
    app.menubar = menubar
    app.focused = None
    return FakeBackend(app)


def menubar_menu(backend, name):
    """The AXMenu under a top-level menu bar item."""
    item = next(c for c in backend.app.menubar.children if c.title == name)
    return item.children[0]


def by_label(page, label):
    return next(a for a in page["actions"] if a["label"] == label)


def test_role_mapping_is_parameterized():
    cases = {
        "AXButton": "button", "AXCheckBox": "checkbox", "AXRadioButton": "radio",
        "AXTextField": "textbox", "AXTextArea": "textbox", "AXSearchField": "searchbox",
        "AXPopUpButton": "combobox", "AXMenuBarItem": "menuitem", "AXMenuItem": "menuitem",
        "AXTabGroup": "tab",
    }
    for raw, expected in cases.items():
        assert tree.role_of(raw) == expected
    assert tree.role_of("AXUnknownThing") is None


@pytest.mark.parametrize("title,desc,help_,expected", [
    ("Title", "Desc", "Help", "Title"),
    ("", "Desc", "Help", "Desc"),
    ("", "", "Help", "Help"),
    ("", "", "", ""),
])
def test_label_resolution_precedence(title, desc, help_, expected):
    backend = make_app()
    element = FakeElement("AXButton", title=title, desc=desc, help_=help_)
    element.parent = backend.app
    assert tree.label_of(backend, element) == expected


def test_secure_fields_are_never_enumerated():
    backend = make_app(buttons=1, secure=True)
    page = _observe(backend)
    assert [a["label"] for a in page["actions"]] == ["Button 0", "Wait for the app to update"]
    assert "s3cret" not in page["text"]


def _observe(backend, bundle="com.test.app"):
    from jev_ultrafast.desktop import DesktopApp

    app = DesktopApp(bundle, backend=backend)
    page = app.observe()
    app.close()
    return page


def test_output_cap_counts_omitted_subtrees():
    backend = make_app(buttons=251)
    page = _observe(backend)
    assert len([a for a in page["actions"] if a["kind"] != "wait"]) == 250
    assert page["omitted_actions"] >= 1


def test_traversal_is_bounded_even_on_hostile_trees():
    bomb = FakeElement("AXGroup", title="root", children=[
        FakeElement("AXGroup", title=f"n{i}", children=[FakeElement("AXButton", title=f"x{i}")])
        for i in range(4000)
    ])
    backend = make_app()
    backend.app.windows[0].children.append(bomb)
    page = _observe(backend)
    assert page["omitted_actions"] >= 1
    assert backend.copy_calls < 3000 * 12  # node budget bounds total backend traffic


def test_closed_menus_are_never_descended_open_menus_are():
    backend = make_app(menubar_items=["File"])
    page = _observe(backend)
    labels = [a["label"] for a in page["actions"]]
    assert "File" in labels  # the menu bar item is pressable
    assert "File item 0" not in labels  # its closed menu is not descended into

    # Opening a menu moves the app's focus into it — that is the open indicator.
    opened = menubar_menu(backend, "File")
    backend.app.focused = opened
    page = _observe(backend)
    assert "File item 0" in [a["label"] for a in page["actions"]]

    backend.app.focused = None  # menu closed again
    page = _observe(backend)
    assert "File item 0" not in [a["label"] for a in page["actions"]]


def test_identical_guards_still_get_distinct_ids():
    from jev_ultrafast.desktop import DesktopApp

    backend = make_app()
    window = backend.app.windows[0]
    twins = [FakeElement("AXButton", title="Twin") for _ in range(2)]  # same role/title/position
    window.children.extend(twins)
    app = DesktopApp(backend.bundle, backend=backend)
    page = app.observe()
    ids = [a["id"] for a in page["actions"] if a["label"] == "Twin"]
    assert len(ids) == 2 and len(set(ids)) == 2  # one id per element, never collapsed
    app.close()


def test_readonly_text_fields_are_not_fill_targets():
    backend = make_app(fields=1)
    readonly = FakeElement("AXTextField", title="ReadOnly", value="locked")  # no writable attrs
    backend.app.windows[0].children.append(readonly)
    page = _observe(backend)
    kinds = {a["label"]: a["kind"] for a in page["actions"]}
    assert kinds.get("ReadOnly") == "click" or "ReadOnly" not in kinds  # offered as click at most
    assert kinds.get("Field 0") == "fill"


def test_windowless_app_lists_no_window_roles():
    backend = make_app(buttons=1)
    backend.app.windows = [backend.app]  # the degenerate macOS AXWindows list
    page = _observe(backend)
    assert page["windows"] == 0


def test_ids_survive_reobservation_for_living_elements():
    from jev_ultrafast.desktop import DesktopApp

    backend = make_app(buttons=2)
    app = DesktopApp(backend.bundle, backend=backend)
    first = app.observe()
    second = app.observe()
    for action in first["actions"]:
        if action["kind"] == "wait":
            continue
        same = by_label(second, action["label"])
        assert same["id"] == action["id"]
    app.close()


def test_ids_are_retired_and_never_reused():
    from jev_ultrafast.desktop import DesktopApp

    backend = make_app(buttons=2)
    app = DesktopApp(backend.bundle, backend=backend)
    first = app.observe()
    dead_id = by_label(first, "Button 0")["id"]
    backend.app.windows[0].children.pop(0)
    second = app.observe()
    assert dead_id not in [a["id"] for a in second["actions"]]
    backend.app.windows[0].children.append(FakeElement("AXButton", title="New"))
    third = app.observe()
    new_id = by_label(third, "New")["id"]
    assert new_id != dead_id and int(new_id[1:]) > int(dead_id[1:])
    app.close()


def test_guard_tracks_position():
    backend = make_app(buttons=1)
    page = _observe(backend)
    button = backend.app.windows[0].children[0]
    button.position = (50, 50)
    page2 = _observe(backend)
    assert by_label(page2, "Button 0")["guard"] != by_label(page, "Button 0")["guard"]


def test_marker_is_sensitive_to_focus_changes():
    from jev_ultrafast.desktop import DesktopApp

    backend = make_app(buttons=1)
    app = DesktopApp(backend.bundle, backend=backend)
    page = app.observe()
    backend.app.focused = backend.app.windows[0].children[0]
    assert not app.fresh(page)
    app.close()


def test_action_space_consumes_the_desktop_table():
    backend = make_app(buttons=2, fields=1, menubar_items=["Edit"])
    page = _observe(backend)
    elements, targets, controls = model.action_space(page["actions"])
    roles = {element["label"]: element for element in elements}
    assert set(roles) >= {"Button 0", "Field 0", "Edit"}
    assert "CLICK" in targets and "TYPE_TEXT" in targets
    assert "WAIT" in controls


class FakeAXModule:
    def __init__(self, copy_code=0):
        self.copy_code = copy_code

    def AXUIElementCopyAttributeValue(self, element, attribute, _):
        return (self.copy_code, "value")

    def AXUIElementSetAttributeValue(self, element, attribute, value):
        return self.copy_code

    def AXUIElementPerformAction(self, element, action):
        return self.copy_code

    def AXUIElementIsAttributeSettable(self, element, attribute):
        return (self.copy_code, True)

    def AXUIElementCopyActionNames(self, element, _):
        return (self.copy_code, ["AXPress"])

    def AXUIElementCreateApplication(self, pid):
        return "app"


class FakeWorkspaceApp:
    def bundleIdentifier(self):
        return "com.test.app"

    def processIdentifier(self):
        return 42


class FakeWorkspace:
    def sharedWorkspace(self):
        return self

    def runningApplications(self):
        return [FakeWorkspaceApp()]


def test_pyobjc_backend_error_mapping():
    element = object()
    ok = PyobjcBackend(ax=FakeAXModule(0), workspace=FakeWorkspace())
    assert ok.copy(element, "AXRole") == "value"
    assert ok.set(element, "AXValue", "x") is True
    assert ok.perform(element, "AXPress") is True
    assert ok.application("com.test.app") == "app"

    empty = PyobjcBackend(ax=FakeAXModule(NO_VALUE), workspace=FakeWorkspace())
    assert empty.copy(element, "AXRole") is None
    refused = PyobjcBackend(ax=FakeAXModule(-999), workspace=FakeWorkspace())
    with pytest.raises(AXError):
        refused.copy(element, "AXRole")
    assert refused.set(element, "AXValue", "x") is False
    assert refused.action_names(element) == []

    gone = PyobjcBackend(ax=FakeAXModule(INVALID_UI_ELEMENT), workspace=FakeWorkspace())
    for call in (lambda: gone.copy(element, "AXRole"), lambda: gone.set(element, "AXValue", "x"),
                 lambda: gone.perform(element, "AXPress"), lambda: gone.action_names(element)):
        with pytest.raises(ElementGone):
            call()


def test_unsupported_attribute_reads_as_absent():
    backend = PyobjcBackend(ax=FakeAXModule(ATTRIBUTE_UNSUPPORTED), workspace=FakeWorkspace())
    assert backend.copy(object(), "AXRole") is None


def test_backend_identity_comparison():
    backend = PyobjcBackend(ax=FakeAXModule(0), workspace=FakeWorkspace())
    marker = object()
    assert backend.same(marker, marker) is True
    assert backend.same(object(), object()) is False


def test_ax_module_import_is_guarded(monkeypatch):
    import jev_ultrafast.desktop.ax as ax_module

    monkeypatch.setitem(sys.modules, "ApplicationServices", None)
    monkeypatch.setitem(sys.modules, "Cocoa", None)
    importlib.reload(ax_module)
    try:
        assert ax_module._ax_module is None
        with pytest.raises(RuntimeError, match="pyobjc"):
            ax_module.PyobjcBackend()
    finally:
        monkeypatch.undo()
        importlib.reload(ax_module)
