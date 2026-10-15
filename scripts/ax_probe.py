#!/usr/bin/env python3
"""Phase-1 spike: probe macOS AX activation routes for Chrome's accessibility tree.

Usage:
    uv run python scripts/ax_probe.py [--bundle-id com.google.Chrome] [--disruptive]

Read-only by default (plus the AXEnhancedUserInterface attribute write and one
throwaway CDP tab that is closed again). `--disruptive` additionally allows the
chrome://accessibility tab and the Chrome relaunch (--force-renderer-accessibility)
candidates. Exit codes: 0 recipe found, 2 chrome UI only, 3 no AX, 4 skipped
(no Chrome / no TCC / non-macOS). No model calls, no paid APIs.
"""

from __future__ import annotations

import argparse
import pathlib
import platform
import subprocess
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ax_probe_verdict as verdict  # noqa: E402

MAX_NODES = 3000
MAX_DEPTH = 25
SETTLE_SECONDS = 3.0
PASSWORD_PAGE = 'data:text/html,<title>jev-probe</title><input type="password" value="s3cret-jev">'

try:
    from ApplicationServices import (  # type: ignore
        AXIsProcessTrusted,
        AXUIElementCopyAttributeValue,
        AXUIElementCreateApplication,
        AXUIElementSetAttributeValue,
    )
    from Cocoa import NSWorkspace  # type: ignore
except ImportError:  # non-macOS or missing dependency: probe reports the skip path
    AXIsProcessTrusted = None


class AX:
    """Thin error-code-aware wrapper over the AX C API."""

    NO_VALUE = -25212
    ATTRIBUTE_UNSUPPORTED = -25205

    def __init__(self):
        self.available = AXIsProcessTrusted is not None

    def copy(self, element, attribute):
        error, value = AXUIElementCopyAttributeValue(element, attribute, None)
        if error in (self.NO_VALUE, self.ATTRIBUTE_UNSUPPORTED):
            return None
        if error:
            raise RuntimeError(f"AXUIElementCopyAttributeValue({attribute}) -> {error}")
        return value

    def set(self, element, attribute, value):
        return AXUIElementSetAttributeValue(element, attribute, value)


def cdp_call(method, **params):
    from browser_harness.helpers import cdp

    return cdp(method, **params)


def cdp_ready() -> bool:
    """True only when the harness daemon is already talking to Chrome (never prompts)."""
    try:
        cdp_call("Browser.getVersion", _response_timeout=2.0)
        return True
    except Exception:  # noqa: BLE001 - any failure means "not ready", not an error
        return False


def find_pid(bundle_id: str) -> int | None:
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == bundle_id:
            return app.processIdentifier()
    return None


def enumerate_tree(ax: AX, root, budget: int) -> tuple[dict[str, int], int]:
    """Count roles under `root` within a node budget. Returns (counts, visited)."""
    counts: dict[str, int] = {}
    visited = 0
    stack = [(root, 0)]
    while stack and visited < budget:
        element, depth = stack.pop()
        visited += 1
        role = ax.copy(element, "AXRole") or "?"
        counts[role] = counts.get(role, 0) + 1
        if depth >= MAX_DEPTH:
            continue
        stack.extend((child, depth + 1) for child in ax.copy(element, "AXChildren") or [])
    return counts, visited


def app_snapshot(ax: AX, app) -> tuple[dict[str, int], int]:
    """Enumerate window subtrees first, then the menu bar with the remaining budget."""
    counts: dict[str, int] = {}
    visited = 0
    for window in ax.copy(app, "AXWindows") or []:
        window_counts, window_visited = enumerate_tree(ax, window, MAX_NODES - visited)
        visited += window_visited
        for role, n in window_counts.items():
            counts[role] = counts.get(role, 0) + n
    menubar = ax.copy(app, "AXMenuBar")
    if menubar:
        menu_counts, menu_visited = enumerate_tree(ax, menubar, max(0, MAX_NODES - visited))
        visited += menu_visited
        for role, n in menu_counts.items():
            counts[role] = counts.get(role, 0) + n
    return counts, visited


def walk_elements(ax: AX, root):
    stack = [(root, 0)]
    while stack:
        element, depth = stack.pop()
        yield element
        if depth < MAX_DEPTH:
            stack.extend((child, depth + 1) for child in ax.copy(element, "AXChildren") or [])


def find_role_value(ax: AX, app, role: str):
    for window in ax.copy(app, "AXWindows") or []:
        for element in walk_elements(ax, window):
            if ax.copy(element, "AXRole") == role:
                return element
    return None


def has_web_content(counts: dict[str, int]) -> bool:
    return counts.get("AXWebArea", 0) > 0


def check_enhanced_ui(ax: AX, app) -> tuple[str | None, str]:
    outcome = ax.set(app, "AXEnhancedUserInterface", True)
    if outcome != 0:
        return None, f"set failed: {outcome}"
    time.sleep(SETTLE_SECONDS)
    counts, _ = app_snapshot(ax, app)
    if has_web_content(counts):
        return "enhanced-ui", "set ok; web content appeared"
    return None, "set ok; no web content appeared"


def masking_probe(ax: AX, app) -> str:
    from browser_harness.admin import ensure_daemon

    ensure_daemon()
    target = cdp_call("Target.createTarget", url=PASSWORD_PAGE, background=True)["targetId"]
    try:
        time.sleep(1.5)
        counts, _ = app_snapshot(ax, app)
        if not counts.get("AXSecureTextField"):
            return "unverified (no AXSecureTextField visible)"
        secure = find_role_value(ax, app, "AXSecureTextField")
        if secure is not None and ax.copy(secure, "AXValue") is None:
            return "verified"
        return "FAILED: secure value readable" if secure is not None else "unverified"
    finally:
        cdp_call("Target.closeTarget", targetId=target)


def omnibox_write_probe(ax: AX, app) -> str:
    omnibox = None
    for window in ax.copy(app, "AXWindows") or []:
        for element in walk_elements(ax, window):
            if ax.copy(element, "AXRole") == "AXTextField":
                description = (ax.copy(element, "AXDescription") or "").lower()
                if "address" in description or "search" in description:
                    omnibox = element
                    break
        if omnibox is not None:
            break
    if omnibox is None:
        return "unverified (omnibox not found)"
    prior = ax.copy(omnibox, "AXValue")
    marker = "jev-ax-probe"
    try:
        if ax.set(omnibox, "AXValue", marker) != 0:
            return "rejected: AXValue write refused"
        read_back = ax.copy(omnibox, "AXValue")
        return f"verified (read-back={'match' if read_back == marker else 'MISMATCH'})"
    finally:
        ax.set(omnibox, "AXValue", prior or "")


def accessibility_page_probe(ax: AX, app) -> tuple[str | None, str]:
    target = cdp_call("Target.createTarget", url="chrome://accessibility", background=True)["targetId"]
    try:
        time.sleep(2.0)
        counts, _ = app_snapshot(ax, app)
        if has_web_content(counts):
            return "accessibility-page", "web content appeared after visiting chrome://accessibility"
        return None, "no web content after visiting chrome://accessibility"
    finally:
        cdp_call("Target.closeTarget", targetId=target)


def relaunch_probe(ax: AX, app_factory, bundle_id: str, app_name: str) -> tuple[str | None, str]:
    cdp_call("Browser.close")
    time.sleep(2.0)
    subprocess.run(["open", "-a", app_name, "--args", "--force-renderer-accessibility"], check=False)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        pid = find_pid(bundle_id)
        if pid:
            time.sleep(SETTLE_SECONDS)
            counts, _ = app_snapshot(ax, app_factory(pid))
            if has_web_content(counts):
                return "relaunch-flag", "web content appeared after relaunch with --force-renderer-accessibility"
            return None, "relaunched with the flag; no web content"
        time.sleep(0.5)
    return None, "relaunch timed out"


def localized_app_name(bundle_id: str, default: str) -> str:
    from Cocoa import NSWorkspace

    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == bundle_id and app.localizedName():
            return app.localizedName()
    return default


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe Chrome macOS AX activation routes")
    parser.add_argument("--bundle-id", default="com.google.Chrome")
    parser.add_argument(
        "--disruptive", action="store_true",
        help="allow the chrome://accessibility tab candidate",
    )
    parser.add_argument(
        "--relaunch", action="store_true",
        help="also relaunch Chrome with --force-renderer-accessibility (implies --disruptive)",
    )
    parser.add_argument("--force-skip", action="store_true", help="report the skip path without probing")
    args = parser.parse_args()

    if platform.system().lower() != "darwin" or args.force_skip:
        print("skip: not running on macOS (or --force-skip)")
        return 4
    if AXIsProcessTrusted is None or not AXIsProcessTrusted():
        print("skip: this process is not AX-trusted. Grant Accessibility access to the host app "
              "(System Settings > Privacy & Security > Accessibility), then re-run.")
        return 4
    pid = find_pid(args.bundle_id)
    if pid is None:
        print(f"skip: no running app with bundle id {args.bundle_id}")
        return 4

    ax = AX()
    app = AXUIElementCreateApplication(pid)
    candidates: list[dict] = []
    counts: dict[str, int] = {}
    recipe = None

    # Candidate 1: baseline read + role read (Chromium enables AX modes when AXRole is read, macOS 14+).
    try:
        role, title = ax.copy(app, "AXRole"), ax.copy(app, "AXTitle")
        counts, visited = app_snapshot(ax, app)
        outcome = f"{role} '{title}' readable; {visited} nodes visited"
        if has_web_content(counts):
            recipe, outcome = "baseline", outcome + "; web content present"
        candidates.append({"name": "baseline+role-read", "outcome": outcome})
    except RuntimeError as error:
        candidates.append({"name": "baseline+role-read", "outcome": f"failed: {error}"})

    # Candidate 2: AXEnhancedUserInterface write (2s debounce in Chromium).
    if recipe is None:
        try:
            found, outcome = check_enhanced_ui(ax, app)
            counts, _ = app_snapshot(ax, app)
            recipe = found
        except RuntimeError as error:
            outcome = f"failed: {error}"
        candidates.append({"name": "enhanced-ui", "outcome": outcome})

    # Masking probe: one throwaway CDP tab with a password field; skipped unless CDP is
    # already usable (never blocks on the macOS "Allow remote debugging" sheet).
    masking = "unverified"
    if cdp_ready():
        try:
            masking = masking_probe(ax, app)
            candidates.append({"name": "masking-probe", "outcome": masking})
        except Exception as error:  # noqa: BLE001 - diagnostic only
            masking = "unverified"
            candidates.append({"name": "masking-probe", "outcome": f"failed: {error}"})
    else:
        candidates.append({"name": "masking-probe",
                           "outcome": "skipped: CDP daemon not connected to Chrome yet "
                                      "(start the inspector once or run browser-harness mac-approve)"})

    # Disruptive candidates, only when allowed, still needed, and CDP is already usable.
    disruptive = args.disruptive or args.relaunch
    if recipe is None and disruptive:
        probes = []
        if cdp_ready():
            probes.append(("accessibility-page", lambda: accessibility_page_probe(ax, app)))
            if args.relaunch:
                app_name = localized_app_name(args.bundle_id, "Google Chrome")
                probes.append(("relaunch-flag",
                               lambda: relaunch_probe(ax, AXUIElementCreateApplication,
                                                      args.bundle_id, app_name)))
        for name, probe in probes:
            try:
                found, outcome = probe()
                recipe = found
            except Exception as error:  # noqa: BLE001 - diagnostic only
                outcome = f"failed: {error}"
            candidates.append({"name": name, "outcome": outcome})
            if recipe:
                break

    # Value-write check on the omnibox, only once web content exists (gates Phase 5's fill).
    value_write = omnibox_write_probe(ax, app) if recipe else "skipped (no web content)"

    for line in verdict.summarize(candidates, counts):
        print(line)
    print(f"value_write: {value_write}")
    print(verdict.masking_line(masking))
    print(verdict.verdict_line(recipe or ("chrome-ui-only" if counts else "none")))
    return verdict.exit_code(recipe or ("chrome-ui-only" if counts else "none"))


if __name__ == "__main__":
    sys.exit(main())
