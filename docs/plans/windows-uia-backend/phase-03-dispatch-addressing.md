# Phase 03 — Platform dispatch + exe-name addressing + MCP/install/doctor

Priority: P2 · Status: Pending · Effort: ~3h · Test scope: S/M (see bottom)

## Context

- Default backend hook: `jev_ultrafast/desktop/app.py:20-23` (`_default_backend`).
- MCP allowlist + messages: `jev_ultrafast/desktop_mcp.py:24` (`DEFAULT_ALLOW`), `:40-44`, `:126-132` (error text says "bundle id").
- Makefile: `check-desktop` hardcodes `check_ax.py` (`Makefile:62-63`). Doctor: `Desktop AX` line (`scripts/doctor.py:163-182`). Installer wording: `scripts/install_mcp.py:47`, `:448-450`.
- Touchpoint inventory: [research-codebase-touchpoints.md](./research-codebase-touchpoints.md) §2, §5.

## Overview

Make the seam callable end-to-end on Windows: platform-conditional default backend, neutral app addressing ("bundle id on macOS, exe basename on Windows") through `DesktopApp` → MCP schema → `JEV_DESKTOP_ALLOW`, per-platform allowlist defaults, and Windows branches in Makefile/doctor/installer wording.

## Key insights from research

- Allowlist is a flat string list — exe names slot in mechanically; but **exe-basename identity is weaker than bundle-id identity** (two different apps can share a basename in different directories), and the expansion plan adds **keyboard synthesis**, which raises the stakes (red-team finding 4). Therefore: allowlist entries support an optional **path-qualified form** (full image path, matched against `QueryFullProcessImageName` output gathered in Phase 1's sweep); bare basenames stay legal for casual use. `type`'s foreground predicate (Phase 2) checks the PID set of the matched entry, so a basename collision cannot redirect keystrokes to another process of the same name. Path-qualified grants are the documented recommendation for any entry the user intends to type into.
- `AXManualAccessibility` best-effort call is already try/except-wrapped (`app.py:40-46`) — Windows just no-ops it (Phase 1). No dispatch needed there.
- `install_mcp.py` has no darwin gate — only macOS wording; the jev-desktop opt-in registration flow works as-is on Windows.

## Requirements

**Functional**
- `_default_backend()`: `sys.platform == "darwin"` → `PyobjcBackend`; `"win32"` → `UiaBackend`; else RuntimeError naming the supported platforms (mirrors existing error style).
- `JEV_DESKTOP_ALLOW` default per platform: `com.google.Chrome` (darwin) / `notepad.exe` (win32). Entries matched per-platform: exact string on macOS; on win32 **case-insensitive** basename OR full-path form (above). Attach error messages reworded ("bundle id (macOS) or exe name (Windows)").
- `desktop_attach` docstring/allowlist docs updated; allowlist entries matched per-platform (no behavior change for existing macOS entries).
- `make check-desktop` dispatches: darwin → `check_ax.py`; win32 → `check_uia.py` (Phase 4); other → actionable skip message.
- Doctor: Windows branch reporting the UIA dependency + a note that elevated targets are automatable only at equal integrity level (UIPI); macOS branch unchanged.

**Non-functional**
- No new config surface beyond what exists (`JEV_DESKTOP_ALLOW` keeps its name and comma-separated format).
- README wording changes belong to Phase 4's sweep; this phase only touches docstrings/error strings users see at runtime.

## Related code

- Modify: `jev_ultrafast/desktop/app.py` (`_default_backend`), `jev_ultrafast/desktop_mcp.py` (default allowlist, docstrings, error text), `Makefile` (target dispatch), `scripts/doctor.py` (win32 branch).
- Tests: `tests/test_desktop_mcp.py`, `tests/test_make_scripts.py`, plus a new dispatch test.

## Implementation steps

1. `_default_backend()` platform dispatch + tests (3 branches via monkeypatched `sys.platform`).
2. Per-platform `DEFAULT_ALLOW` + attach/allowlist error text; update MCP tests asserting the new strings.
3. Makefile `check-desktop` dispatch; extend `tests/test_make_scripts.py` contract.
4. Doctor Windows branch; offline contract test (fake platform, fake deps).
5. Installer wording sweep (macOS-only phrasing → dual-platform) — strings only, no logic.

## Success criteria

- On macOS: `make check-desktop`, doctor, installer behave exactly as today (existing tests green).
- On a faked win32 platform: dispatch selects `UiaBackend`, default allowlist is `notepad.exe`, error messages name the exe-name semantics.
- No credential or allowlist bypass introduced: attach outside the allowlist still refuses on both platforms.

## Risk assessment

- **Weaker allowlist identity on Windows** (basename collision) → path-qualified entry form + `type` PID-set foreground predicate implemented (not deferred); docs recommend path-qualified grants for type targets. Enforcement upgrade (mandate full-path) stays deferred unless spike shows need.
- **Case-sensitivity mismatch between layers** (red-team finding 12) → single comparison helper shared by attach + allowlist layers, one test row proves `Notepad.exe` matches `notepad.exe`.
- Multi-instance exe ambiguity → lowest-PID policy documented in `application()` docstring; disambiguation deferred (plan-level decision).
- Dispatch creep (e.g. Linux branches) → explicitly out of scope; RuntimeError names supported platforms.

## Test scope (per test-budget)

Mapped behaviors → tests: backend dispatch (3 platform rows, 1 parameterized), per-platform default allowlist (2), attach refusal outside allowlist on win32 semantics (1), path-qualified entry matching (1), case-insensitive matching via shared helper (1), Makefile dispatch (1), doctor win32 branch (1), installer wording is strings-only (0 tests). **≈ 8 test functions — size S/M, within ceiling; the 2 security rows are red-team-mapped additions.**
