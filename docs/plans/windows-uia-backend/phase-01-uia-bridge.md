# Phase 01 — UIA bridge: UiaBackend behind the Protocol

Priority: P2 · Status: Pending · Effort: ~7h · Test scope: L (see bottom)

## Context

- Seam: `jev_ultrafast/desktop/ax.py:55-84` — `AXBackend` Protocol (application / copy / set / perform / is_settable / action_names / same).
- Precedent to mirror: `PyobjcBackend` guarded module import (`ax.py:9-16`), injectable ctor (`ax.py:87-97`), `_normalize` (`ax.py:147-152`).
- Research: [research-uia-ecosystem.md](./research-uia-ecosystem.md) §1-§5; touchpoints: [research-codebase-touchpoints.md](./research-codebase-touchpoints.md) §1, §3.
- Repo rules (`AGENTS.md`): never retry a mutation; tests offline, no paid APIs.

## Overview

New module `jev_ultrafast/desktop/uia.py`: `UiaBackend` implementing the 7-method Protocol over `uiautomation`, **translating AX-vocabulary strings to UIA properties/patterns internally** so `tree.py`/`app.py` are untouched. Windows-only dependency, marker-gated; import guarded so macOS/Linux test runs stay green.

## Key insights from research

- `uiautomation` 2.0.29 walks raw trees (`GetChildren`, `WalkControl(maxDepth)`) and reads per-element patterns (`GetPattern`) — maps 1:1 onto `copy`/`action_names`. Imports fail off-Windows (unconditional `comtypes`/`windll`) → guarded import + lazy RuntimeError like `ax.py`.
- VB6 `ThunderRT6*` controls surface through the **Oleacc MSAA→UIA proxy**: Name/ControlType/State/BoundingRectangle available; **no AutomationId equivalent**, no Text pattern → guards must anchor on RuntimeId + (ControlType, Name) path + BoundingRectangle (same shape as today's scheme).
- Fill via `ValuePattern.SetValue` + read-back is spec-confirmed; `IsReadOnly` is the settable probe. `UIA_E_ELEMENTNOTAVAILABLE` → `ElementGone`.
- UIA has no per-app root: `application(exe_name)` returns a chosen main-window element. Resolve exe→PID(s) with Toolhelp32Snapshot via `ctypes` (no new runtime dep); fallback decision (psutil, win32-marked) left to implementation if ctypes proves brittle — `inferred`.
- No property searches inside walks — walk raw children; budgets stay in `tree.py`.

## Requirements

**Functional**
- `UiaBackend(uia=None)` — injectable module handle for offline tests, mirroring `PyobjcBackend(ax=None)`.
- Translation map (all inside `uia.py`):
  - `copy(el, ROLE)` → AX-style role string synthesized from ControlType (`AXButton`, `AXTextField`, `AXCheckBox`, `AXMenuBarItem`...); **`AXSecureTextField` synthesized when `IsPassword` is true** (keeps `tree.py:169` skip working without walker changes).
  - `copy(el, TITLE)` → Name; `copy(el, DESCRIPTION)` → full description / `HELP` → help text when available (both feed `label_of`, `tree.py:71-76`); `copy(el, VALUE)` → ValuePattern.Value (None when pattern absent); `copy(el, ENABLED)` → IsEnabled.
  - `copy(el, MENU_BAR)` → the app's menu bar element (`tree.py:196-198` reads it unconditionally); None when the app exposes none (Windows menu behavior itself is a spike question — Phase 4).
  - `copy(el, POSITION)` / `copy(el, SIZE)` → BoundingRectangle split into two tuples (mirrors `_normalize`).
  - `copy(el, CHILDREN)` → child element list; `copy(el, PARENT)` → TreeWalker parent; `copy(el, WINDOWS)` → process's top-level windows; `copy(el, FOCUSED_ELEMENT)` → focused element.
- `is_settable(el, VALUE)` = ValuePattern present AND not IsReadOnly. `set(el, VALUE, text)` = SetValue; returns False when refused.
- `action_names(el)` → `["AXPress"]` when Invoke/Toggle/SelectionItem/ExpandCollapse pattern present (pattern→priority order decided in implementation, documented in-module). `perform(el, "AXPress")` → Invoke, falling back Toggle.Invoke → SelectionItem.Select → ExpandCollapse.
- `same(a, b)` → CompareElements (or RuntimeId comparison — spike decides, see Phase 4).
- `application(exe_name)` → None when not running; else main-window element (lowest-PID policy for multi-instance, documented). Basename comparison is **case-insensitive** on win32 (Windows names are; keeps attach and allowlist layers agreeing). Resolution enumerates PIDs via Toolhelp32Snapshot **and full image paths via `QueryFullProcessImageName` in the same sweep** — the path feeds Phase 3's path-qualified allowlist matching. `set(el, "AXManualAccessibility", True)` returns False silently (Windows has no analogue) — do not raise.

**Non-functional**
- Dep: `"uiautomation>=2.0.29,<3; sys_platform == 'win32'"` in `pyproject.toml` (pinned ≥2.0.29 — 2.0.21-27 were yanked).
- No event-handler registration, no threads (pull model only); no property-search calls inside walks.
- The offline **fake `uia` module mirrors the 2.0.29 release source specifically** (not GitHub master — the research line numbers cite master), so offline proofs and the on-box spike test the same API surface.
- Guarded import catches `(ImportError, OSError, ValueError, AttributeError)` — a force-installed `uiautomation` off-Windows can raise non-ImportError from module-level `ctypes.windll` calls — with the same actionable message.
- `uiautomation` sets Per-Monitor DPI awareness at import (process-wide side effect): acceptable (execution is pattern-based, not coordinate-based), but `uia_probe.py` output must note bounding rects are physical px under that mode.
- macOS behavior byte-identical: no edits to `ax.py` semantics.

## Related code

- Create: `jev_ultrafast/desktop/uia.py`.
- Modify: `pyproject.toml` (dependency), `jev_ultrafast/desktop/__init__.py` (export only if needed).
- Untouched by design: `tree.py`, `app.py`, `desktop_mcp.py`.

## Implementation steps

1. Add the win32-marked dependency; confirm `uv lock`/`uv build` succeed on macOS without installing it.
2. Skeleton: guarded import + `UiaBackend.__init__(uia=None)` raising the actionable RuntimeError off-Windows (mirror `ax.py:87-97` wording style).
3. Property translation (`copy`) incl. role synthesis, IsPassword → `AXSecureTextField`, BoundingRectangle split.
4. Pattern translation: `is_settable`, `set`, `action_names`, `perform`, pattern-priority order.
5. Identity `same()` + `ElementGone` on ELEMENTNOTAVAILABLE (COMError inspection).
6. `application(exe_name)` resolution: Toolhelp32Snapshot → PID set → root-control window children filtered by ProcessId → lowest-PID main window.
7. Offline tests against a fake `uia` module (mirroring `FakeAXModule`, `tests/test_desktop.py:324-385`, incl. the `sys.modules` reload-guard pattern `:398-411`).

## Success criteria

- `uv run pytest` green on macOS with the new suite; `uv build` passes.
- Fake-driven tests prove every Protocol method translated correctly (table-driven, `{typical, boundary, invalid}` per mapped behavior).
- Existing desktop tests pass unmodified.

## Risk assessment

- **RuntimeId / CompareElements instability on MSAA-proxied content** (`unknown`) → guard scheme does not depend on it alone; on-box spike (Phase 4) verifies before deploy.
- **comtypes/uiautomation on newest Python** (`unknown`) → user deploys on a chosen Windows env; record tested version in spike checklist.
- **ctypes Toolhelp32 brittleness** → documented fallback: psutil, win32-marked.
- Scope guard: any walker change discovered necessary here is a design smell — stop and revisit translate-at-backend instead of patching `tree.py`.

## Test scope (per test-budget)

Mapped behaviors → tests: import guard (2: missing-lib RuntimeError incl. non-ImportError path, marker gating), property/label translation (1 parameterized table, ~8 rows: ROLE per ControlType, TITLE/DESCRIPTION/HELP fallback order, MENU_BAR present/absent, case-insensitive exe match), IsPassword→secure (1), BoundingRectangle split (1), VALUE is_settable/set/read-back (3: settable-readonly-refused, write-sticks, pattern-absent), perform priority (1 table, 4 rows), error mapping (2: ELEMENTNOTAVAILABLE→ElementGone, generic COMError→AXError), same() (1), exe resolution via fake (3: found, not-running-None, lowest-PID policy), AXManualAccessibility no-op (1). **≈ 16 test functions — size L; one over the 15 ceiling, justified: the red-team audit added 4 unmapped behaviors (opt-in no-op, PID policy, generic error branch, label trio) that each map to a distinct requirement.**
