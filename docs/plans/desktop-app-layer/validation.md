# Validation Log — desktop-app-layer plan

Validated 2026-10-15. **Mode: autonomous** — the plan was produced in an unattended run, so the critical-questions interview ran with recommended answers documented instead of a live interview. Every decision below can be overridden by editing the phase files before implementation; nothing here is load-bearing without your consent.

## Q1 — Should the desktop layer also drive web content inside Chrome, or stay on app chrome UI?

- **Recommended (chosen)**: Phase-1 spike decides; plan works for both outcomes. Chrome app UI (menu bar, tabs, omnibox, window controls) is the guaranteed floor; web content (`AXWebArea`) only if the spike finds a reproducible activation recipe (it failed on first probe — `research-digest.md` finding 18).
- **Why**: web content in Chrome is already served by the existing CDP browser layer; coupling the desktop layer to an unverified activation recipe would put the whole plan on a fragile foundation.
- **Override**: force web-content scope by pre-verifying a recipe before Phase 2.

## Q2 — How much power should `desktop_attach` have by default?

- **Recommended (chosen)**: allowlist, default `com.google.Chrome` only, opt-in via `JEV_DESKTOP_ALLOW`; `make install` registers only `jev-browser` by default (phase-04 threat model).
- **Why**: an AX-trusted process can execute shell via Terminal or approve TCC dialogs; a prompt-injected coding agent must not get arbitrary-app control silently (red-team #2, #6).
- **Override**: set `JEV_DESKTOP_ALLOW` / `--server all` — the plan supports both, explicitly.

## Q3 — One shared MCP server or a separate `jev-desktop`?

- **Recommended (chosen)**: separate server (user's message already allowed this: "có thể thêm riêng mcp cho desktop app riêng nếu cần"). Confirmed by research: browser server's globals/tools would collide, and desktop needs `attach` semantics, not `navigate` (digest, recommended approach 2).
- **Override**: merging is possible later by making `mcp_server.py` multiplex, but no phase depends on it.

## Q4 — pyobjc direct vs a wrapper library (atomacos)?

- **Recommended (chosen)**: direct pyobjc. atomacos is 2021-stale, GPLv2, and itself a pyobjc wrapper (digest finding 12). Verified live on this machine (pyobjc 12.2.2 reads Chrome's app/menu/window AX tree).
- **Override**: none sensible; atomacos adds a stale GPL dependency for no capability.

## Q5 — Does `fresh()` need the browser's exact marker semantics on day one?

- **Recommended (chosen)**: mirror the browser split — guard (attributes + identity anchor) for click/fill, enriched marker for DONE/BLOCKED and pre-fill. Red-team found the naive "guard + marker for everything" both too weak (DONE validation) and too strict (focus churn) — fixed in phases 2–3.
- **Override**: stricter marker-for-all if you distrust AX identity anchors; expect more spurious re-observes.

## Q6 — Test depth?

- **Recommended (chosen)**: repo convention — offline pytest contracts with a fake backend (no paid APIs, per AGENTS.md) + a live no-model check script against real Chrome with skip-guards and opt-in mutations (user: "chú ý thêm mục test thật cẩn thận, dùng app chrome để test thử nếu cần"). ~45 test functions across phases, each mapped to a named behavior (test-budget contract), ceilings respected.
- **Override**: `--test-budget=N` on a later `hi-craft` run, or ask for exhaustive tests.

## Decision summary

| Decision | Choice | Where |
|----------|--------|-------|
| Web-content scope | Spike-gated (Q1) | phase-01 |
| Attach power | Allowlist default Chrome (Q2) | phase-04, plan.md |
| MCP topology | Separate `jev-desktop` (Q3) | phase-04 |
| AX binding | Direct pyobjc (Q4) | phase-02 |
| Freshness semantics | Browser-split (Q5) | phase-02, phase-03 |
| Test strategy | Offline contracts + live opt-in check (Q6) | all phases |

**Recommendation: proceed.** Plan is internally consistent, red-teamed (15/15 findings applied), and its biggest unknown (Chrome activation) is isolated in a cheap first phase whose worst case de-scopes cleanly rather than blocking.
