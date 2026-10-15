# Phase 1 — Chrome AX activation spike

## Overview

- **Priority**: P1 (blocks scope of Phases 2–3)
- **Status**: Pending
- **Effort**: 3h (red-team re-baseline)
- **Description**: Determine, on this machine (macOS 26.6 + Chrome 154), a repeatable recipe that makes Chrome expose its full AX tree — especially web content (`AXWebArea`) — and record the verdict. Everything downstream depends on this.

## Context

- Research: [research-digest.md](./research-digest.md) findings 14–19 (activation attempts failed with `-25208`/`-25205`; `AXManualAccessibility` is Electron-only; `AXEnhancedUserInterface` is debounced 2s in Chromium `chrome_browser_application_mac.mm`).
- Related: `scripts/check_guards.py` (style to mirror), `browser_harness.helpers.cdp` (CDP fallback candidate).

## Key insights from research

- Reading app-level attributes works today with zero activation (menu bar, windows, window controls verified live).
- Four untested activation candidates: `--force-renderer-accessibility` launch flag; `chrome://accessibility` toggle; window-restored (not minimized) timing; CDP `Accessibility.enable`.
- `AXToolbar` returned `-25205` while the window was minimized — probes must use a restored window.

## Requirements

**Functional**
- A committed probe script that can be re-run by anyone: `uv run python scripts/ax_probe.py [--bundle-id com.google.Chrome]`.
- It must test, in order, and report per-candidate success/failure with AX error codes: (1) plain read + `AXRole` read; (2) `AXEnhancedUserInterface` set + 3s wait; (3) window state (restored vs minimized); (4) with-relaunch flag `--force-renderer-accessibility`; (5) `chrome://accessibility` toggle (open tab, read, close); (6) CDP `Accessibility.enable` via browser-harness as last resort.
- **Disruptive candidates are flag-gated**: (4) and (5) run only behind `--disruptive` (they relaunch Chrome / open-close a tab in the user's session). Default run is read-only + the `AXEnhancedUserInterface` write.
- Success = an enumeration containing `AXWebArea` (web content) AND stable omnibox/tab-strip roles, printed with counts.
- **Value-write check** (gates Phase 5's omnibox fill): on a successful activation, write `kAXValue` on the omnibox and read it back; report writability and whether Chrome masks secure fields (`AXSecureTextField` value read attempt → expect mask/failure). Phase 5 may only ship fill+read-back if this check passed.
- **Secret-masking verdict** is part of the output: `MASKING=<verified|unverified>`.

**Non-functional**
- No paid API calls, no model calls. Read-only plus at most one throwaway tab. Never mutates user settings (the `--disruptive` candidates are explicit, opt-in exceptions and restore/clean up after themselves).
- The verdict formatter lives in a **stdlib-only module** (e.g. `scripts/ax_probe_verdict.py`) or behind a guarded import, so importing it from pytest never pulls pyobjc (keeps Linux `uv run pytest` green).
- Script exits 0 on recipe-found, 2 on "chrome UI only", 3 on no AX at all (CI-mappable).

## Architecture

Single script, stdlib + pyobjc (+ browser-harness only for candidate 6). Output: human-readable log + machine-readable verdict line `VERDICT=<recipe>|chrome-ui-only|none`. Full findings written to [spike-activation.md](./spike-activation.md).

## Related code

- Create: `scripts/ax_probe.py`, `scripts/ax_probe_verdict.py` (stdlib-only formatter), `docs/plans/desktop-app-layer/spike-activation.md`
- Modify: none

## Implementation steps

1. Add `pyobjc-framework-ApplicationServices`/`Cocoa`/`Quartz` as marker-gated dev deps (see Phase 2 step 1 — land the dependency first).
2. Implement probe skeleton: NSWorkspace lookup by bundle id, `AXUIElementCreateApplication(pid)`, attribute reader with error-code reporting; verdict formatter in the stdlib-only module.
3. Implement the 6 candidates; disruptive ones behind `--disruptive`; relaunch Chrome with the flag only behind an explicit `--relaunch` CLI flag (never kill the user's browser silently).
4. Run against real Chrome with a restored window; iterate until a recipe is found or all fail; run the value-write + masking checks if activation succeeded.
5. Write `spike-activation.md`: chosen recipe, observed roles for omnibox/tabs/toolbar, error codes, masking verdict, and the **scope verdict** (does Phase 2 target web content or chrome UI only?).

## Success criteria

- Verdict line produced and recorded; recipe reproducible on a second run; masking verdict recorded.
- If `none`: Phase 2/3 scope is confirmed as chrome UI + menu bar, and the web-content limitation is documented in the plan and README (Phase 5); Phase 5's fill check is dropped (it was gated on this verdict).

## Test scope

- Mapped criteria: script exit codes; verdict line format. 
- Size: **S** — 2–3 offline pytest cases for the verdict formatter only (probe itself is a live tool, like `check_guards.py`).

## Risk assessment

- Chrome may gate web AX behind internal state no external attribute can set → mitigation: verdict `chrome-ui-only` is an acceptable outcome; desktop layer still covers every non-browser app plus browser chrome UI; CDP remains the web-content path.
- Relaunching Chrome is disruptive → flag-gated, opt-in, never kills without confirmation.
