"""macOS Accessibility backend: one small Protocol plus the pyobjc adapter.

All pyobjc imports live here, behind a guarded module-level import so the rest of
the package (and the test suite on any OS) can import and run without pyobjc.
"""

from typing import Any, Protocol

try:
    import ApplicationServices as _ax_module
    from Cocoa import NSWorkspace as _workspace
    from CoreFoundation import CFEqual as _cf_equal
except ImportError:  # non-darwin or dependency missing: PyobjcBackend reports it lazily
    _ax_module = None
    _workspace = None
    _cf_equal = None

NO_VALUE = -25212
ATTRIBUTE_UNSUPPORTED = -25205
ACTION_UNSUPPORTED = -25208
INVALID_UI_ELEMENT = -25202

ROLE = "AXRole"
TITLE = "AXTitle"
DESCRIPTION = "AXDescription"
HELP = "AXHelp"
VALUE = "AXValue"
POSITION = "AXPosition"
SIZE = "AXSize"
ENABLED = "AXEnabled"
CHILDREN = "AXChildren"
PARENT = "AXParent"
WINDOWS = "AXWindows"
FOCUSED_ELEMENT = "AXFocusedUIElement"
MENU_BAR = "AXMenuBar"
MENUS = "AXMenus"  # currently open menus, exposed on the application element
ATTRIBUTES = "AXAttributes"


class AXError(RuntimeError):
    """An AX call failed with a non-recoverable error code."""

    def __init__(self, operation: str, code: int):
        super().__init__(f"{operation} failed with AX error {code}")
        self.code = code


class ElementGone(AXError):
    """The referenced UI element no longer exists (kAXErrorInvalidUIElement)."""

    def __init__(self, operation: str = "AX call"):
        super().__init__(operation, INVALID_UI_ELEMENT)


class AXBackend(Protocol):
    """The only surface the desktop layer needs from any accessibility framework."""

    def application(self, bundle_id: str) -> Any:
        """The app's AX element, or None when the app is not running."""
        ...

    def copy(self, element: Any, attribute: str) -> Any:
        """Read one attribute. None when absent or unsupported; ElementGone when the ref died."""
        ...

    def set(self, element: Any, attribute: str, value: Any) -> bool:
        """Write one attribute. False when the write is refused."""
        ...

    def perform(self, element: Any, action: str) -> bool:
        """Perform a trusted action (AXPress...). False when refused."""
        ...

    def is_settable(self, element: Any, attribute: str) -> bool:
        """Whether one attribute is writable (AXValue on a read-only field is not)."""
        ...

    def action_names(self, element: Any) -> list[str]:
        """Actions the element supports (AXPress, AXPick, ...)."""
        ...

    def same(self, a: Any, b: Any) -> bool:
        """Element identity: whether two refs point at the same UI element."""
        ...


class PyobjcBackend:
    """AXBackend over pyobjc. `ax`/`workspace` are injectable for offline tests."""

    def __init__(self, ax: Any = None, workspace: Any = None):
        self._ax = ax if ax is not None else _ax_module
        self._workspace = workspace if workspace is not None else _workspace
        if self._ax is None or self._workspace is None:
            raise RuntimeError(
                "pyobjc (ApplicationServices/Cocoa) is required for desktop automation on macOS. "
                "Install on macOS: uv sync (the dependency is marker-gated to darwin)."
            )

    def application(self, bundle_id: str) -> Any:
        for app in self._workspace.sharedWorkspace().runningApplications():
            if app.bundleIdentifier() == bundle_id:
                return self._ax.AXUIElementCreateApplication(app.processIdentifier())
        return None

    def copy(self, element: Any, attribute: str) -> Any:
        error, value = self._ax.AXUIElementCopyAttributeValue(element, attribute, None)
        if error in (NO_VALUE, ATTRIBUTE_UNSUPPORTED):
            return None
        if error == INVALID_UI_ELEMENT:
            raise ElementGone(f"copy {attribute}")
        if error:
            raise AXError(f"copy {attribute}", error)
        return self._normalize(attribute, value)

    def set(self, element: Any, attribute: str, value: Any) -> bool:
        error = self._ax.AXUIElementSetAttributeValue(element, attribute, value)
        if error == INVALID_UI_ELEMENT:
            raise ElementGone(f"set {attribute}")
        return error == 0

    def perform(self, element: Any, action: str) -> bool:
        error = self._ax.AXUIElementPerformAction(element, action)
        if error == INVALID_UI_ELEMENT:
            raise ElementGone(f"perform {action}")
        return error == 0

    def is_settable(self, element: Any, attribute: str) -> bool:
        error, settable = self._ax.AXUIElementIsAttributeSettable(element, attribute)
        if error == INVALID_UI_ELEMENT:
            raise ElementGone(f"is_settable {attribute}")
        return error == 0 and bool(settable)

    def action_names(self, element: Any) -> list[str]:
        error, names = self._ax.AXUIElementCopyActionNames(element, None)
        if error == INVALID_UI_ELEMENT:
            raise ElementGone("copy action names")
        return list(names) if not error else []

    def same(self, a: Any, b: Any) -> bool:
        if _cf_equal is None:
            return a is b
        try:
            return bool(_cf_equal(a, b))
        except TypeError:
            return a is b

    def _normalize(self, attribute: str, value: Any) -> Any:
        if attribute == POSITION and hasattr(value, "x"):
            return (value.x, value.y)
        if attribute == SIZE and hasattr(value, "width"):
            return (value.width, value.height)
        return value
