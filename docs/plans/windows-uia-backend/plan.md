---
title: "Windows UIA desktop backend + expansion actions"
description: "Add UiaBackend behind the existing AXBackend seam (uiautomation, win32-marker-gated), exe-name app addressing, select/scroll/keyboard expansion actions on Windows, platform dispatch in MCP/install/doctor, and a Windows live-check + on-box spike kit."
status: pending
priority: P2
effort: 20h
issue:
branch: develop
tags: [feature, backend, experimental]
blockedBy: []
blocks: []
created: 2026-10-16
---

# Plan: Windows UIA desktop backend + expansion actions

## Overview

Fulfil the "reserved seam" the desktop layer promised: a second desktop backend for **Windows UI Automation** beside the macOS AX backend, so the same loop — page → indexed element table → operation + target id → trusted execution — drives Windows apps, with classic **VB6/Win32** apps as the motivating target (user deploys on a real Windows box later). Scope mode: **EXPANSION** (user-selected) — adds `select`, `scroll`, and keyboard synthesis action kinds on Windows; Linux AT-SPI stays deferred.

Evidence: [research-uia-ecosystem.md](./research-uia-ecosystem.md) (library landscape, VB6/MSAA-bridge exposure, gotchas) + [research-codebase-touchpoints.md](./research-codebase-touchpoints.md) (line-level inventory of AX-specific code). Predecessor: [desktop-app-layer](../desktop-app-layer/plan.md) (implemented).

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [UIA bridge — UiaBackend behind the Protocol](./phase-01-uia-bridge.md) | Pending |
| 2 | [Expansion action kinds — select / scroll / keyboard](./phase-02-expansion-kinds.md) | Pending |
| 3 | [Platform dispatch + exe-name addressing + MCP/install/doctor](./phase-03-dispatch-addressing.md) | Pending |
| 4 | [Windows live-check + docs sweep + on-box spike kit](./phase-04-live-check-spike-docs.md) | Pending |

## Key decisions (from research)

- **Library**: `uiautomation>=2.0.29,<3; sys_platform == 'win32'` (Apache-2.0, active, raw tree walk + per-element patterns, sync, DPI-aware at import; installs anywhere but imports only on Windows — matches the pyobjc marker pattern). pywinauto rejected (wrapper layer fights per-element pattern reads; 1.0.0b1 published 2026-10-15, unreviewed). WinAppDriver rejected (dormant, separate driver process).
- **Translate-at-backend**: `UiaBackend` accepts the AX-vocabulary attribute/action strings (`AXRole`, `AXTitle`, `AXValue`, `AXPress`, ...) and translates to UIA properties/patterns internally. `tree.py`/`app.py` control flow stays untouched; walker stays shared.
- **Addressing**: exe basename (`notepad.exe`) as the Windows app key; `application(exe)` re-resolves per observe via process enumeration → main-window element (UIA has no per-app root — research-inferred). MCP wire param stays `app`; allowlist semantics become per-platform (bundle id / exe basename) with the weaker-identity caveat documented.
- **Identity**: `same()` via UIA CompareElements/RuntimeId; guards keep the existing attributes + parent-path + position scheme (BoundingRectangle split into AXPosition/AXSize in the backend). RuntimeId stability is `unknown` → gated by the on-box spike.
- **Expansion kinds appear only when the backend reports capability** — macOS loop (click/fill/wait) is unchanged and regression-guarded.
- **Verification without a Windows dev box**: everything above the seam is offline-testable (`UiaBackend(uia=None)` + fake module, mirroring `FakeAXModule`); the live parts ship as `scripts/check_uia.py` + a spike checklist the user runs **on the Windows machine** (Notepad/Win32 first; VB6 verdicts gate select/fill promises on legacy apps).

## Deferred (explicitly)

- Linux AT-SPI backend; macOS parity for scroll and keyboard synthesis (`CGEventPost`); multi-instance exe disambiguation beyond lowest-PID policy; OCR/vision fallback; elevated/UAC target automation (UIPI — documented limitation, not solved).

## Success criteria

- `uv run ruff check .`, `uv run pytest`, `uv build` pass on macOS with zero Windows deps installed; existing desktop tests untouched in behavior.
- On a Windows box: `desktop_attach("notepad.exe")` → observe indexed elements → click/fill verified by read-back → select/scroll/keyboard kinds work on native UIA content; `python scripts/check_uia.py` prints `PASS: N desktop UIA checks; no model calls` or skips with an actionable message.
- README/desktop README claims stay consistent: the "reserved seam, deliberately unimplemented" line is replaced by the Windows scope statement.

## Red Team Review

See [red-team.md](./red-team.md) — 1 adversarial reviewer on the written plan; findings adjudicated before hand-off.

## Validation Log

See [validation.md](./validation.md) — scope-challenge answers (EXPANSION; offline + live-check deliverable; Win32-standard target) recorded from the user 2026-10-16.
