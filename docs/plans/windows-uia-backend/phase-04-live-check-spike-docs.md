# Phase 04 — Windows live-check + docs sweep + on-box spike kit

Priority: P2 · Status: Pending · Effort: ~4h · Test scope: S (see bottom)

## Context

- Live-check template: `scripts/check_ax.py` (`decide_skip` pure function `:41-55`) + offline contract `tests/test_check_ax.py:21-35`.
- Probe precedent: `scripts/ax_probe.py` (predecessor spike tooling, `docs/plans/desktop-app-layer/spike-activation.md`).
- README claims to sweep: `README.md` lines 5, 10, 36, 47, 118, 152-165, 253-295, 333-338, 354-362, 375, 381; `jev_ultrafast/desktop/README.md:50-51` ("reserved seam, deliberately unimplemented"); `docs/architecture.md:9, 35-59`.
- Repo rules: verify actual final outcomes independently; keep README claims consistent; no paid APIs.

## Overview

Ship everything the user needs to verify **on the real Windows machine** (they deploy later; no Windows available during development): a skip-guarded `scripts/check_uia.py` live check (Notepad), a `scripts/uia_probe.py` spike probe, and a spike checklist doc whose verdicts gate the plan's promises on VB6/legacy content. Then one coherent README/docs consistency sweep.

## Key insights from research

- Open `unknown`s that only the on-box spike can close: RuntimeId/`same()` stability across reopen; VB6 grid pattern availability; modal-window visibility through the MSAA bridge; tested Python version for comtypes/uiautomation; menu-bar equivalence on Windows (macOS `MIN_MENU_ITEMS` assertion has no guaranteed analogue).
- The predecessor plan's spike-first pattern worked: probe script + verdict doc, before trusting the API contract.

## Requirements

**Functional**
- `scripts/check_uia.py`: mirrors `check_ax.py` structure — `decide_skip` pure function (not Windows / `uiaautomation` import fails / `notepad.exe` not running → actionable skip reason), then real checks. **Default run is read-only** (attach → observe → assert the element table: roles mapped, ids stable across re-observe): fill-with-sentinel and menu click are **behind `--mutations`** (mirrors `check_ax.py:95-96,143` — red-team finding 9). Mutation flow: fill Notepad with a sentinel → read-back verified from the element tree (not from our own write); menu interaction uses the two-step click → re-observe dance (Win32 menus may materialize popups only after open — red-team finding 3). Prints `PASS: N desktop UIA checks; no model calls`.
- `scripts/uia_probe.py`: read-only probe dumping the UIA tree summary for a target exe (roles, patterns, RuntimeId presence, bounding rects) — the VB6 diagnostic tool.
- `docs/plans/windows-uia-backend/spike-windows.md`: checklist the user runs on the box — **step zero: API-surface check** (import `uiautomation` 2.0.29, dump attributes/pattern-class names, diff against the offline fake's surface — red-team finding 8); Notepad smoke via `check_uia.py` (read-only, then `--mutations`); **menu-model question**: does ControlType_Menu inherit the closed-menu pruning rule harmlessly, and does UIA's FocusedElement land inside the menu element when a popup opens (the open-indicator `tree.py:177-184` relies on)? Record verdict + whether the Windows pruning-bypass contingency flag is needed; VB6 app probe steps (launch their exe, run `uia_probe.py`, record which patterns appear on ThunderRT6 controls, reopen-app RuntimeId stability, modal visibility, grid scroll verdict); a verdict table mapping each plan promise (fill/click/select/scroll/type) to confirmed/broken on VB6.
- Docs sweep: README + desktop README + architecture doc state the Windows scope accurately (what works, what is spike-gated, UIPI/elevated limitation, allowlist exe-name caveat, keyboard trust note); `desktop/README.md:50-51` "reserved seam" line replaced; predecessor `plan.md` status corrected to completed (done in this plan's creation, verified here).

**Non-functional**
- No model calls anywhere in the scripts; no paid APIs; scripts skip cleanly on macOS (so `make build`/CI stay green).
- Demonstration footage rule respected if anything is recorded (original speed) — optional, not required.

## Related code

- Create: `scripts/check_uia.py`, `scripts/uia_probe.py`, `docs/plans/windows-uia-backend/spike-windows.md`.
- Modify: `README.md`, `jev_ultrafast/desktop/README.md`, `docs/architecture.md`, `Makefile` (only if `check_uia` needs its own target name), `tests/test_check_uia.py` (new).

## Implementation steps

1. `decide_skip` for the Windows environment; offline contract tests (mirror `tests/test_check_ax.py`).
2. Live-check body: attach → observe → fill/read-back → menu click → independent outcome verification (read the sentinel from the Notepad element tree, not from our own write).
3. `uia_probe.py` read-only dump (tree summary, pattern inventory per node).
4. `spike-windows.md` checklist with verdict table placeholder.
5. README/architecture sweep end-to-end (the full line list above), keeping claims↔evidence↔model-call counts consistent (`AGENTS.md` rule).
6. Run full gates on macOS: `uv run ruff check .`, `uv run pytest`, `node --check jev_ultrafast/static/app.js`, `uv build`.

## Success criteria

- `scripts/check_uia.py` on macOS prints the actionable skip (wrong platform), never a traceback; contract tests prove each skip branch.
- The spike kit is self-contained: a person on a Windows box with the repo + a VB6 exe can produce the verdict table without asking questions.
- Every README statement about desktop scope is true on both platforms after the sweep.

## Risk assessment

- **Spike reveals a broken promise** (e.g. VB6 fill unreliable) → the verdict table exists precisely to catch this; outcome = scope note in README + follow-up plan, not silent claim inflation.
- **Menu-click verification flakiness on Notepad across Windows 10/11** (menu implementations differ) → pick the flattest verifiable interaction (edit menu → select all → type sentinel → read back); keep assertion minimal.
- **Docs drift** → sweep is one pass at the end of the plan, after code is final; `check_guards`-style consistency re-read before hand-off.

## Test scope (per test-budget)

Mapped behaviors → tests: `decide_skip` branches (2), check-script body contract against a fake backend (1), probe-script output contract (1), Makefile target if added (1). Docs have no unit tests (verified by the sweep + gates). **≈ 5 test functions — size S, within ceiling.**
