# Phase 3 — Action execution + freshness guards

## Overview

- **Priority**: P1
- **Status**: Pending
- **Effort**: 4h
- **Description**: Complete `DesktopApp` with `fresh(page, action)` and `act(action, page, text)` — trusted AX execution guarded by immediate re-verification, mirroring the browser layer's staleness discipline.

## Context

- Discipline to mirror: `fresh()` re-checks identity+semantics (`browser.py:88-98`); `act()` refuses stale pages (`browser.py:100-102`); execution re-resolves and validates the target immediately before input (`browser.py:144-168`); a decision is consumed before mutation (AGENTS.md "Never retry a browser mutation"; `agent.py:90-92`).
- Research: findings 20 (`AXPress` verified as available action; `kAXValueAttribute` write `inferred`), risks 4 (keyboard synthesis unverified — **out of v1**), 8 (background/frontmost behavior `unknown`).

## Requirements

**Functional**
- `fresh(page, action=None)`, mirroring the browser split (`browser.py:88-98`):
  - For `click`/`fill`: re-resolve the cached AXRef and compare its **full guard tuple `[role, label, enabled, value, path, position]`** — the identity anchor (parent-path + position) is mandatory; an attribute-only match on a duplicate-label element is not freshness (red-team #1). Marker equality is **not** required (frontmost/focus churn must not cause spurious StaleState — red-team #9).
  - For `DONE`/`BLOCKED`-style decisions (no action): the enriched `marker` alone decides.
- `act(action, page, text=None)`:
  1. Guard: `if not self.fresh(page, action): raise StaleState(...)` — **before any mutation**.
  2. `click` → re-resolve the element by guard (including path+position) immediately before performing, verify `AXUIElementCopyActionNames` ∋ `AXPress`, then `AXUIElementPerformAction(el, "AXPress")`. The re-resolution + compare closes the TOCTOU window as tightly as the platform allows (the browser analogue is `browser.py:144-168`'s re-resolve + hit-test; acknowledge the residual gap honestly: AX has no atomic test-and-press).
  3. `fill` → same re-resolution, verify writable, `set_attribute(el, kAXValue, text)`, then **read-back verify** equality; mismatch ⇒ `StaleState` (no retry inside `act` — the caller decides, mirroring "inspect before retrying").
  4. `wait` → `time.sleep(0.1)`, no guard needed.
  5. Returns `{"executed": action["id"]}`.
- Dead-element errors (`-25202 InvalidUIElement`) at guard or perform time ⇒ `StaleState` with an "Observe again" message, never a raw AX error.
- `close()` releases the cached refs; safe to call twice.
- Explicit non-goal: keyboard synthesis (`CGEventPost`), menu-item deep traversal execution, `select`/scroll kinds — recorded as backlog.

**Non-functional**
- Same contract style as browser: never log or return secure values; errors carry actionable messages ("Observe again", not stack traces).

## Architecture

`app.py` grows `fresh`/`act`; `ax.py` gains `copy_action_names`/`perform_action`/writable-value probe on the Protocol. Execution path: `guard(re-read) → backend.perform/set → return` — no caching of guard results across the mutation.

## Related code

- Modify: `jev_ultrafast/desktop/app.py`, `jev_ultrafast/desktop/ax.py`
- Modify: `tests/test_desktop.py` (extend)

## Implementation steps

1. Extend `AXBackend` Protocol + `PyobjcBackend` (action names, perform action, value write, enabled/readonly probes).
2. Implement `fresh()` (guard re-read + marker compare).
3. Implement `act()` routing with the guard-first order; wire `text` for fill.
4. Tests: stale-guard rejection happens **before** backend.perform is called (spy asserts zero calls); read-back mismatch ⇒ StaleState with backend untouched afterward; wait needs no guard; double-`close` safe; `fresh` False on dead ref (fake ref invalidated).
5. Update `jev_ultrafast/desktop/README.md` with the act contract.

## Success criteria

- A fake-backend session can: observe → mutate the fake tree → `act` raises `StaleState` without calling the backend; observe → act → read-back verified, `{"executed": "e3"}`.
- Property that matters (from AGENTS.md): **no code path performs a mutation on a stale decision**.

## Test scope

- Mapped criteria → tests: guard-before-mutation (critical rule, 1 test + stale variants parameterized: dead ref / changed label / changed value / **moved element** (path+position) / changed action names); marker **irrelevance** for click/fill (focus flip between observe and act does NOT spuriously fail) and **requirement** for DONE-style decisions; click action-name verification (missing AXPress ⇒ refuse, no mutation); fill read-back verify (equal / mismatch); disabled element refused; dead-element `-25202` ⇒ StaleState not AXError; wait; idempotent close.
- Size: **M** (~11 test functions).

## Risk assessment

- AXPress on background apps may no-op or auto-frontmost (risk 8) → document observed behavior in Phase 5 live check; do not silently activate apps (`inferred`: never call `AXRaise` ourselves).
- `kAXValue` write rejected by some fields → read-back verify turns silent corruption into explicit `StaleState`; keyboard fallback stays backlog (needs its own TCC analysis).
