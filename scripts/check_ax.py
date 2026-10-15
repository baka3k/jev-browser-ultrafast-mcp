#!/usr/bin/env python3
"""Live desktop AX check against real Chrome. Read-only by default; no model calls.

Usage:
    uv run python scripts/check_ax.py [--mutations] [--bundle-id com.google.Chrome]

Skips cleanly (exit 0) when the desktop layer cannot run here: non-macOS, pyobjc
missing, no Accessibility permission, Chrome not running, or Chrome running
without any window. Mutations are opt-in and additionally gated on the Phase-1
spike verdict (docs/plans/desktop-app-layer/spike-activation.md).
"""

from __future__ import annotations

import argparse
import pathlib
import platform
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from jev_ultrafast.desktop import DesktopApp, tree  # noqa: E402

SPIKE_DOC = pathlib.Path(__file__).resolve().parent.parent / "docs/plans/desktop-app-layer/spike-activation.md"
MIN_MENU_ITEMS = 5


def parse_verdict(text: str) -> str | None:
    """The VERDICT= line from the spike doc: a recipe name, chrome-ui-only, or None."""
    for line in text.splitlines():
        if line.startswith("VERDICT="):
            return line.split("=", 1)[1].strip() or None
    return None


def read_verdict(path: pathlib.Path) -> str | None:
    return parse_verdict(path.read_text(encoding="utf-8")) if path.is_file() else None


def decide_skip(*, darwin: bool, pyobjc_ok: bool, trusted: bool, chrome_running: bool,
                window_count: int | None = None) -> str | None:
    """The skip decision as a pure function; None means the check may run."""
    if not darwin:
        return "not macOS"
    if not pyobjc_ok:
        return "pyobjc missing — run 'uv sync'"
    if not trusted:
        return ("no Accessibility permission for this host app — "
                "System Settings > Privacy & Security > Accessibility")
    if not chrome_running:
        return "Chrome is not running"
    if window_count is not None and window_count == 0:
        return "Chrome is running without any window — open a window and re-run"
    return None


def check_table(page: dict) -> list[str]:
    """Read-only assertions over one observation. Returns human-readable failures."""
    failures = []
    actions = [a for a in page["actions"] if a["kind"] != "wait"]
    menu_items = [a for a in actions if a["role"] == "menuitem"]
    if len(menu_items) < MIN_MENU_ITEMS:
        failures.append(f"menu bar has {len(menu_items)} pressable menuitem(s), expected >= {MIN_MENU_ITEMS}")
    if page["windows"] < 1:
        failures.append("no readable window title")
    if len(actions) > tree.MAX_ACTIONS:
        failures.append(f"element table has {len(actions)} actions, expected <= {tree.MAX_ACTIONS}")
    if "s3cret" in page["text"] or any("s3cret" in str(a.get("value", "")) for a in actions):
        failures.append("a secret marker value leaked into the element table")
    ids = [a["id"] for a in actions]
    if len(set(ids)) != len(ids):
        failures.append("duplicate element ids in one observation")
    return failures


def raw_roles(backend, app) -> set[str]:
    """Roles visible through the raw AX bridge, bounded like the walker."""
    roles: set[str] = set()
    visited = 0
    stack = [app]
    while stack and visited < tree.MAX_NODES:
        element = stack.pop()
        visited += 1
        role = backend.copy(element, "AXRole")
        if role:
            roles.add(role)
        stack.extend(backend.copy(element, "AXChildren") or [])
    return roles


def main() -> int:
    parser = argparse.ArgumentParser(description="Live desktop AX check (no model calls)")
    parser.add_argument("--bundle-id", default="com.google.Chrome")
    parser.add_argument("--mutations", action="store_true",
                        help="also run the value-write check (gated on the spike verdict)")
    parser.add_argument("--force-skip", action="store_true", help="exercise the skip path")
    args = parser.parse_args()

    darwin = platform.system().lower() == "darwin"
    pyobjc_ok, trusted, chrome_running, window_count = True, True, True, None
    backend = None
    if not args.force_skip:
        try:
            from ApplicationServices import AXIsProcessTrusted  # noqa: F401 - the TCC probe

            from jev_ultrafast.desktop.ax import PyobjcBackend

            backend = PyobjcBackend()
            trusted = bool(AXIsProcessTrusted())
            # Probe windows only once trusted: untrusted reads raise AXError, which would
            # otherwise be swallowed here and misreported as a missing dependency.
            if trusted:
                app = backend.application(args.bundle_id)
                chrome_running = app is not None
                if chrome_running:
                    window_count = len(tree.windows_of(backend, app))
        except (ImportError, RuntimeError):
            pyobjc_ok = False

    reason = decide_skip(darwin=darwin, pyobjc_ok=pyobjc_ok, trusted=trusted,
                         chrome_running=chrome_running, window_count=window_count)
    if reason or args.force_skip:
        print(f"skip: {reason or 'forced by --force-skip'}")
        print("PASS: 0 desktop AX checks; no model calls (skipped)")
        return 0

    checks, failures = 0, []
    app = DesktopApp(args.bundle_id, backend=backend)
    try:
        page = app.observe()
        failures.extend(check_table(page))
        checks += 1

        # A recorded activation recipe must not silently regress (Chrome auto-updates).
        verdict = read_verdict(SPIKE_DOC)
        if verdict not in (None, "none", "chrome-ui-only"):
            web_roles = raw_roles(backend, backend.application(args.bundle_id))
            if "AXWebArea" not in web_roles:
                failures.append("spike verdict expects web content but none is visible — re-run scripts/ax_probe.py")
        checks += 1

        if args.mutations:
            if verdict in (None, "none", "chrome-ui-only"):
                print("note: --mutations is gated off by the spike verdict; the value-write check "
                      "ships once scripts/ax_probe.py reports VERDICT=<recipe> and MASKING=verified")
            else:
                failures.append("--mutations has no implementation for a verified recipe yet — "
                                "add the omnibox fill + finally-restore block (phase-05)")
            checks += 1
    except (RuntimeError, ValueError) as error:
        failures.append(f"observation failed: {error}")
    finally:
        app.close()

    for failure in failures:
        print(f"FAIL: {failure}")
    if failures:
        return 1
    print(f"PASS: {checks} desktop AX checks; no model calls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
