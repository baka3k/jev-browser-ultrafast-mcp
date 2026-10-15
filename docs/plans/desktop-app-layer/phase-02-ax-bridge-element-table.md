# Phase 2 — AX bridge + element table

## Overview

- **Priority**: P1
- **Status**: Pending
- **Effort**: 6h (red-team re-baseline)
- **Description**: Create `jev_ultrafast/desktop/` — a pyobjc-backed AX bridge behind a small `AXBackend` seam and a tree walker that produces the same indexed element table as `snapshot.js`. Read-only in this phase (no actions yet).

## Context

- Interface to mirror: `Browser.observe/fresh/act/close` (`jev_ultrafast/browser/browser.py:44-113`), element shape `{id, kind, label, role, value, node}` (`snapshot.js:61-104`), caps + `omitted_actions` (`snapshot.js:99-100`).
- Research: findings 11 (pyobjc surface; `AXUIElementCopyFocusedUIElement` NOT wrapped — use system-wide element + `kAXFocusedUIElement`), 14–15 (verified Chrome app/window/menu reads), 19 (role inventory), risk 6 (8.6k menu items → caps mandatory).

## Key insights from research

- AX elements are not long-lived stable handles (risk 5): the observer owns a `node-id → AXUIElementRef` cache that **persists across observations on the session** (mirroring the browser's in-page `WeakMap`, `snapshot.js:3-8`) and is **revalidated** on every observe — an id keeps pointing at the same element while it lives; a dead element's id is retired and never reused. This is what makes cross-observation id references safe for the MCP flow (red-team #3).
- Guards must carry an **identity anchor**, not just attributes: duplicate role+label+value elements (two "OK" buttons, repeated bookmarks) are otherwise indistinguishable, and a re-bound ref can pass an attribute-only guard (red-team #1). Guards therefore include a root-to-element **parent-path** and the element's **position/size**, re-checked at act time (Phase 3).
- pyobjc imports must never leak to non-darwin platforms (`uv run pytest` must stay green cross-platform).

## Requirements

**Functional**
- `AXBackend` Protocol (`observe`-relevant reads only): `app_element(bundle_id|pid)`, `copy_attribute(el, attr)`, `set_attribute(el, attr, value)` (used by Phase 3), `perform_action(el, action)` (Phase 3), `element_at_path(...)` helper. Single production impl `PyobjcBackend`; tests use a `FakeBackend` fed from a literal AX tree fixture.
- `walk(backend, app)` → element table dict:
  `{app, title, windows, text, actions, marker, guards, omitted_actions, fingerprint}`.
  - Roles mapped to the ARIA-ish vocabulary: `AXButton→button`, `AXCheckBox→checkbox`, `AXRadioButton→radio`, `AXTextField/AXTextArea→textbox`, `AXSearchField→searchbox`, `AXPopUpButton→combobox`, `AXMenuBarItem/AXMenuItem→menuitem`, `AXTabGroup→tab`; unmapped roles are skipped for actions.
  - Kinds (v1): pressable → `click`; editable (`AXTextField`/`AXTextArea` with writable `AXValue`) → `fill`; **no `select`/scroll in v1**.
  - Labels: `AXTitle` → `AXDescription` → `AXHelp` → `AXValue` (text fields only); never `AXSecureTextField` values (skip field entirely, like `snapshot.js:9`). `text` preview reads only from the attached app's frontmost window (masking of web-area secrets must be verified by the Phase-1 spike before any fill+read-back ships in Phase 5).
  - **Output caps**: 250 actions; 6000-char `text` preview; everything skipped counted in `omitted_actions`.
  - **Traversal budgets (distinct from output caps)**: `max_nodes` (3000) and `max_depth` (25) hard-stop the walk early; **never descend into a closed `AXMenu`** (children are enumerated only while the menu is open, capped at 40) — the probe's 8.6k bookmark items live under closed menus. Skipped-by-budget subtrees count once in `omitted_actions`, not per node.
  - `guards[node]` = `[role, label, enabled, value, path, position]` — attributes + identity anchor (parent-path hash + AXPosition/AXFrame) per element (red-team #1).
  - `marker` (validated only for DONE/BLOCKED-style decisions, Phase 3) = cheap app-level tuple: window count + window titles, frontmost window title, focused element role+label+value, action count, open-menu state (red-team #9: enriched so sheets/dialogs/focus flips move it).
  - `fingerprint(state)` = sha256 over the semantic content (mirror `browser.py:115-117`).
- `DesktopApp` facade: `DesktopApp(bundle_id, backend=None)` → `attach` lazily, `observe()`, `close()`. Backend defaults resolved lazily (import inside factory) so `app.py` imports cleanly on any OS. The id cache and its revalidation live here (session scope).

**Non-functional**
- Design patterns, explicit: **Adapter/Strategy** (`AXBackend` — pyobjc now, UIA/AT-SPI later), **Facade** (`DesktopApp` mirrors `Browser`'s 4-call contract), **Dependency Injection** (backend param → fakes in tests). No deeper abstraction than this (YAGNI).
- Ruff clean (line-length 120, E/F/I); package docstrings mirror `browser/` tone.

## Architecture

```
jev_ultrafast/desktop/
├── __init__.py   # exports DesktopApp, StaleState  (like browser/__init__.py)
├── ax.py         # AXBackend Protocol + PyobjcBackend (all pyobjc imports live here)
├── tree.py       # pure walker: backend + app element -> element table (no pyobjc imports)
├── app.py        # DesktopApp facade; StaleState(ValueError)
└── README.md     # interface doc, mirrors browser/README.md
```
Data flow: `NSWorkspace → pid → AXUIElement → walk() → table` — walker is pure (dict-in/dict-out) and fully unit-testable with the fake.

## Related code

- Create: `jev_ultrafast/desktop/{__init__,ax,tree,app}.py`, `jev_ultrafast/desktop/README.md`, `tests/test_desktop.py`
- Modify: `pyproject.toml` (deps: `pyobjc-framework-ApplicationServices>=12,<13; sys_platform == "darwin"`, plus Cocoa + Quartz with the same marker — bounded per repo pinning style, red-team #15)

## Implementation steps

1. Add marker-gated pyobjc deps; `uv lock && uv sync`; confirm `uv build` unaffected on the dep graph.
2. `ax.py`: Protocol + `PyobjcBackend` (thin, error-code → exceptions: `-25212 NoValue` → `None`, `-25208`/`-25205`-class → `AXError(code)`, `-25202 InvalidUIElement` → `ElementGone`); pyobjc imported via **guarded module-level import** (`try: import ApplicationServices / except ImportError: AppServices = None`) or injected as a constructor argument — both keep the backend mockable and Linux-importable (red-team #13; methods-only lazy imports are not patchable).
3. `tree.py`: walker with role map, label resolution, **traversal budgets + closed-menu rule**, guards (with identity anchor), marker, fingerprint (pure functions).
4. `app.py`: `DesktopApp` facade + `StaleState` + the **session-persistent, revalidated id cache**.
5. `tests/test_desktop.py`: fake-backend contracts (see test scope).
6. `jev_ultrafast/desktop/README.md`.

## Success criteria

- `DesktopApp("com.google.Chrome", backend=FakeBackend(...)).observe()` produces a table the existing `model.action_space()` consumes unchanged (regression-checked by a test importing `model.action_space`).
- `uv run ruff check . && uv run pytest && uv build` green; no pyobjc import on the test path.

## Test scope

- Mapped criteria → tests: role mapping (parameterized AX→ARIA table); label resolution precedence; secure-field exclusion; output caps produce `omitted_actions` (typical/boundary: exactly 250, 251); traversal budgets early-stop without visiting budget-exhausted subtrees (fake tree with a bomb node proves visit count); closed-menu rule (children of closed `AXMenu` never visited); id cache: id stable across re-observe for a living element, retired (never reused) for a dead one; guard carries path+position and they change when the element moves; marker sensitivity (focus flip / dialog ⇒ changed marker); `PyobjcBackend` error-code mapping (mocked AX module injected, 0/-25205/-25212/-25202); cross-platform import guard.
- Size: **M→L** (~13 test functions, parameterized where tabular; red-team #13 seam makes the mocked-backend tests possible).

## Risk assessment

- AX tree shape varies per app → walker is defensive: every attribute read is optional, missing ⇒ skip element, never raise.
- Traversal cost on huge trees → caps + depth limit; revisit after live probe timing.
