---
title: "Desktop-app automation layer (macOS AX) + jev-desktop MCP"
description: "Add a desktop-app layer that reuses jev's indexed element-table loop over the macOS Accessibility API, with a separate jev-desktop MCP server, offline contract tests, and a live Chrome AX check."
status: completed
priority: P2
effort: 22h
issue: 
branch: develop
tags: [feature, backend, experimental]
blockedBy: []
blocks: []
created: 2026-10-15
---

# Plan: Desktop-app automation layer (macOS AX)

## Overview

Replicate the jev loop — page → indexed element table → operation + target id → trusted execution — for **desktop apps on macOS** via the Accessibility (AX) API. New package `jev_ultrafast/desktop/` mirrors the `browser/` layer contract (`observe/fresh/act/close`), a standalone `jev-desktop` MCP server lets coding agents drive desktop apps with no API keys, and testing follows the repo split: offline pytest contracts (fake AX backend) + a live no-model check script against real Chrome. Evidence base: [research-digest.md](./research-digest.md) (repo refs + live probes on this machine: macOS 26.6.2, Chrome 154, pyobjc 12.2.2).

Scope mode: **HOLD** (auto-selected; user asked for clean design patterns, a separate MCP if needed, and careful tests — no stretch goals, no test reduction). macOS-only; Windows UIA / Linux AT-SPI stay a reserved seam, no code. No OCR/vision.

## Phases

| Phase | Name | Status |
|-------|------|--------|
| 1 | [Chrome AX activation spike](./phase-01-activation-spike.md) | Pending |
| 2 | [AX bridge + element table](./phase-02-ax-bridge-element-table.md) | Pending |
| 3 | [Action execution + freshness guards](./phase-03-actions-guards.md) | Pending |
| 4 | [jev-desktop MCP + install/doctor](./phase-04-desktop-mcp-install.md) | Pending |
| 5 | [Live Chrome check + docs + hardening](./phase-05-live-check-docs.md) | Pending |

## Key decisions (from research)

- **Direct pyobjc** (`pyobjc-framework-ApplicationServices` + Cocoa/Quartz, `sys_platform == "darwin"` marker). No atomacos (stale 2021, GPLv2).
- **Separate MCP server** `jev-desktop` (own entry point + SERVERS registry in `install_mcp.py`); browser server's globals/tools would collide.
- **Activation spike first** (Phase 1): AXEnhancedUserInterface write failed (`-25208`) on this stack; web-content (`AXWebArea`) scope is gated on the spike verdict. Chrome **app UI** (menu bar, window controls, tabs, omnibox) is verified working regardless.
- **Same element-table shape** as `snapshot.js` (`{id, kind, label, role, value, node}` — `node` is hard-required by `model.action_space()`, `model.py:161`), kinds `click/fill/wait` only in v1; traversal budgets, not just table caps (Chrome probe showed ~8.6k menu items).
- **Trust boundary**: `desktop_attach` is allowlisted (`JEV_DESKTOP_ALLOW`, default `com.google.Chrome` only); `make install` registers `jev-browser` by default — `jev-desktop` is explicit opt-in.
- **Testing**: offline pytest with a fake `AXBackend`; live check in `scripts/check_ax.py` mirroring `check_guards.py` (skip-guarded, mutations opt-in via `--mutations`); doctor gains an AX-permission check.

## Deferred (explicitly)

- Windows/Linux backends (Windows UIA since picked up by [windows-uia-backend](../windows-uia-backend/plan.md); Linux AT-SPI still deferred), OCR/vision fallback, keyboard-synthesis (`CGEventPost`) path, `Agent` loop genericization (today it constructs `Browser` at `agent.py:20`), demo-inspector UI for desktop, scroll actions.
- Note: "existing brains consume the table unchanged" is scoped to `model.action_space()` (kinds/fields) and the MCP path. The full Python `Agent` loop additionally reads `page["url"]` (`model.py:214`, `agent.py:136`) and stays browser-only until genericization.

## Success criteria

- `make build` passes on macOS and Linux (desktop imports guarded; pyobjc marker-gated).
- A coding agent can: `desktop_attach("com.google.Chrome")` → observe indexed elements (menu bar, tabs, omnibox, window controls) → `desktop_act` → verified outcome; zero model calls, zero API keys; attach is allowlist-enforced (default Chrome only).
- Offline tests prove: element-table contract, guard-stale rejection **before** mutation, never-retry, caps; live script prints `PASS: N desktop AX checks; no model calls` or skips with an actionable message.

## Red Team Review

See [red-team.md](./red-team.md) — 3 reviewers (Security, Assumptions, Failure Modes); findings adjudicated 2026-10-15; accepted items applied to phase files.

## Validation Log

See [validation.md](./validation.md) — critical questions asked in autonomous mode; recommended options documented; user may override before implementation.
