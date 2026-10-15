# Spike: Chrome AX activation is chrome-ui-only — 2026-10-16

[inline:log-writer]

## Context

Phase 1 of the desktop-app-layer plan had to decide whether the AX layer can see Chrome's web content (`AXWebArea`) or only app chrome UI. `scripts/ax_probe.py` probes six activation candidates against the running browser.

## Change

- Verdict recorded in `docs/plans/desktop-app-layer/spike-activation.md`: `VERDICT=chrome-ui-only`, `MASKING=unverified`, exit code 2. The `AXEnhancedUserInterface` write fails with `-25208` on macOS 26 + Chrome 154, reproducing the planning probes.
- `AXWindows` on a windowless Chrome returns the application element itself (role `AXApplication`); the walker filters to real `AXWindow` roles and `check_ax` treats windowless as a skip condition, not a failure.
- The menu bar is fully readable and pressable: 11 top-level items, actions `[AXCancel, AXPress, AXPick]`.

## Impact

Desktop layer v1 targets chrome UI + menu bar only; web content stays with the CDP browser layer. The omnibox fill check in `check_ax --mutations` is gated off until a probe run reports a recipe plus a verified masking verdict. `make check-desktop` exits 0 with an actionable skip message on this machine (Chrome runs windowless here); it reports PASS once a real Chrome window is open.

## Decision

Accept `chrome-ui-only` as a first-class outcome rather than coupling the layer to an unverified activation recipe (the four remaining candidates — `--force-renderer-accessibility` relaunch, chrome://accessibility, CDP `Accessibility.enable`, window-timing — stay probeable via `ax_probe.py --disruptive --relaunch` once CDP is approved).

## References

- probe: scripts/ax_probe.py (verdict formatter: scripts/ax_probe_verdict.py)
- evidence: docs/plans/desktop-app-layer/spike-activation.md
- commit: 47c470f
