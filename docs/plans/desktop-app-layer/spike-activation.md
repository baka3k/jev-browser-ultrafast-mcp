# Spike: Chrome AX activation — verdict

Date: 2026-10-16. Machine: macOS (Darwin 25.6.0 arm64), Chrome running, pyobjc 12.2.2.
Command: `uv run python scripts/ax_probe.py` (default, read-only + enhanced-ui write; `--disruptive`
candidates unavailable because CDP was not connected — Chrome's "Allow remote debugging" sheet
was never approved in this session).

## Verdict

```
VERDICT=chrome-ui-only
MASKING=unverified
value_write: skipped (no web content)
```

Exit code 2. **Scope consequence (per phase-01): Phase 2–3 target chrome UI + menu bar only.**
Web content (`AXWebArea`) stays the CDP browser layer's job. Phase 5's omnibox fill check is
gated off by this verdict (check_ax handles a gated-off mutation section by design).

## Evidence (probe output)

```
[baseline+role-read] AXApplication 'Chrome' readable; 3000 nodes visited
[enhanced-ui] set failed: -25208
[masking-probe] skipped: CDP daemon not connected to Chrome yet
VERDICT=chrome-ui-only
```

- `AXEnhancedUserInterface` write fails with `-25208` — reproduces research-digest finding 18
  (same error on macOS 26 + Chrome 154 in the planning probes).
- Menu bar is fully readable and **pressable**: 11 top-level `AXMenuBarItem`s; raw
  `AXUIElementCopyActionNames` on "Chrome" returned `[AXCancel, AXPress, AXPick]`.
- Follow-up read with **no Chrome window open**: `AXWindows` returned a 1-element list holding the
  **application element itself** (`AXRole=AXApplication`, not `AXWindow`) while `AXMainWindow` /
  `AXFocusedWindow` still answered. Matches research finding 15; the walker must filter
  `AXWindows` entries to real `AXWindow` roles (implemented in phase-02).
- With no window, the menubar subtree alone exhausts the 3000-node budget (bookmark menus) —
  confirms red-team finding #5: traversal needs node/depth budgets *and* the closed-menu rule,
  not just output caps.

## Unknowns remaining

- Web-content activation (needs `--disruptive` run with CDP approved, or a restored window;
  re-run `scripts/ax_probe.py --disruptive` after `browser-harness mac-approve`).
- Chrome's secure-field masking over AX (`MASKING=unverified`) — phase-05 ships no fill+read-back
  until this is `verified`.
- Omnibox value writability (`value_write: skipped`).
