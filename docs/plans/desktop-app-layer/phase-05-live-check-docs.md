# Phase 5 — Live Chrome check + docs + hardening

## Overview

- **Priority**: P2
- **Status**: Pending
- **Effort**: 3h
- **Description**: Live no-model verification against real Chrome (`scripts/check_ax.py`), documentation for the new layer, and the full repo checks green end-to-end.

## Context

- Template: `scripts/check_guards.py` (real local browser, asserts outcomes, prints `PASS: N browser guard checks; no model calls`, stays out of pytest).
- Research: findings 13 (TCC attribution), 14–15 (verified reads), risk 2 (omnibox/tab roles must be re-probed with restored window — Phase 1's `spike-activation.md` supplies the recipe).

## Requirements

**Functional**
- `scripts/check_ax.py` (skip-guarded, never fails `make build`):
  1. Skip cleanly (exit 0, actionable message) when: non-darwin, pyobjc missing, `AXIsProcessTrusted()` False, Chrome not running, **or Chrome running with no windows** (`AXWindows` degenerate case, `research-digest.md:129-133` — red-team #15).
  2. Attach Chrome (bundle id), apply the Phase-1 activation recipe if web content is in scope.
  3. Read-only assertions (default run): menu bar enumerates ≥ 5 `menuitem` pressable entries; ≥ 1 window with title; element table ≤ 250 with stable ids; **no secure values** anywhere in the table; **runtime regression check** — if `spike-activation.md`'s verdict says web content, assert `AXWebArea` presence at runtime, else fail loudly with "activation recipe regressed — re-run scripts/ax_probe" (red-team #15: a Chrome auto-update must not silently flip scope while the script prints PASS).
  4. **Mutations are opt-in** (`--mutations`, red-team #8): omnibox `fill` + read-back and one harmless focus click, each with restore discipline — capture the prior omnibox value first, restore it in a `finally`; close any opened menu with `AXCancel` in the same `finally`; never leave user state changed on crash. Gated additionally on the Phase-1 value-write verdict.
  5. Footer: `PASS: N desktop AX checks; no model calls`.
- Docs: `README.md` (desktop layer section + MCP tools table row + `make install` note), `docs/architecture.md` (third layer + updated diagram), `jev_ultrafast/desktop/README.md` finalized in Phase 2/3 — link it.
- `Makefile`: `make check-desktop` target (runs `check_ax.py`); `make build` unchanged (stays offline/skippable).

**Non-functional**
- README claims, examples, raw evidence, and model-call counts stay consistent (AGENTS.md): the live check makes **zero** model calls; docs must say exactly that.
- Never commit (AGENTS.md) — implementation leaves the tree clean for the user to commit.

## Architecture

`check_ax.py` composes only public pieces: `DesktopApp` + phase-1 recipe helper. Assertions are plain `assert` with messages; skip path is a first-class outcome, not an exception.

## Related code

- Create: `scripts/check_ax.py`
- Modify: `README.md`, `docs/architecture.md`, `Makefile`

## Implementation steps

1. Implement skip-guard chain first (including the windowless-Chrome case); test each skip on this machine (unset TCC simulation via flag `--force-skip`).
2. Implement the read-only assertions + runtime verdict check; run against real Chrome with a restored window; tune budgets if traversal is slow (target: `observe()` < 1s for Chrome app UI).
3. Implement the mutation section behind `--mutations` with the restore discipline (prior value, `finally` restore, `AXCancel`); gate on the Phase-1 value-write verdict.
4. Docs: README section (incl. `JEV_DESKTOP_ALLOW` + opt-in install), architecture layer 3, Makefile `make check-desktop` target.
5. Run the full gate: `uv run ruff check . && uv run pytest && node --check jev_ultrafast/static/app.js && node --check jev_ultrafast/browser/snapshot.js && uv build && uv run python scripts/check_ax.py`.

## Success criteria

- `make check-desktop` on this machine prints the PASS footer with real Chrome; on a machine without TCC/Chrome it exits 0 with the reason.
- All AGENTS.md checks green; README/MCP table/doctor outputs mutually consistent.

## Test scope

- Mapped criteria → tests: offline-only unit tests for the script's pure helpers (skip-decision function: parameterized over the 5 skip conditions incl. windowless Chrome; mutation-scope decision: read-only vs `--mutations` vs verdict-gated-off; assertion helpers over fake tables). Live behavior itself is the script's job, not pytest's.
- Size: **S** (~4 test functions).

## Risk assessment

- Flake: AX timing after activation → retries with short sleeps around activation (bounded, like `Browser.observe`'s 10×20ms loop); a flaky live script is worse than a skipping one — mutations stay behind `--mutations` and read-only checks are the default.
- User-state side effects → restore discipline in `finally` + the allowed-mutation whitelist (omnibox fill + focus, menu open/cancel) is code-reviewed against "never change user data"; omnibox text never navigates (value write only, no `AXConfirm`).
