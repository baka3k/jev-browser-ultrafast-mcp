# Phase 4 — jev-desktop MCP server + install/doctor integration

## Overview

- **Priority**: P2
- **Status**: Pending
- **Effort**: 6h (red-team re-baseline)
- **Description**: Standalone stdio MCP server `jev-desktop` (`desktop_attach / desktop_observe / desktop_act / desktop_close`), registered by a generalized `scripts/install_mcp.py` (SERVERS registry), with `doctor` gaining an Accessibility check.

## Threat model (red-team #2)

An AX-trusted process can observe and mutate **any** app: `fill` into Terminal is arbitrary shell execution; `click` on a TCC "Allow" dialog is a permission-boundary bypass. Therefore:

- `desktop_attach` is **allowlist-enforced**: `JEV_DESKTOP_ALLOW` (comma-separated bundle ids, default `com.google.Chrome`). Attaching anything else returns an error naming the env var. No name-based fuzzy attach outside the allowlist.
- The allowlist is a Python-side check, not security theater: it bounds what a *prompt-injected coding agent* can attach to by default. It is not a sandbox — document that an operator who sets `JEV_DESKTOP_ALLOW=*` accepts arbitrary-app control.
- Registration default stays `jev-browser`; `jev-desktop` reaches agent configs only by explicit opt-in (below), keeping the AX surface out of third-party-relayed agent hosts unless requested.

## Context

- Pattern to copy: `jev_ultrafast/mcp_server.py` (module-global single session `mcp_server.py:36-69`; `@server.tool()` async fns returning `json.dumps(result, indent=2)`; error-as-JSON; zero model calls, zero API keys).
- Registration to generalize: `scripts/install_mcp.py` — `SERVER_NAME`/`ENTRY_POINT` constants feed the `Agent` registry at import time (`install_mcp.py:27-28, 199+`); `server_argv()` (`install_mcp.py:42-49`); `make install` (`Makefile:50-54`); doctor (`scripts/doctor.py:60-208`).
- Research: findings 5–6, 9; risk 3 (TCC attribution for agent-spawned servers → doctor must detect, not assume).

## Requirements

**Functional**
- `jev_ultrafast/desktop_mcp.py`, `MCPServer("jev-desktop")`, tools:
  - `desktop_attach(app: str)` — **allowlist-checked** bundle id (see threat model); resolves pid via NSWorkspace. Closes any previous session.
  - `desktop_observe()` — element table (same formatting style as `jev_observe`: `elements[]` with `id/kind/label/value/role`, `text_preview`, counts).
  - `desktop_act(action_id: str, text: str | None = None)` — re-observe → find id → act → report executed + new counts; `StaleState` ⇒ `{"error": "..."}` instructing re-observe.
  - `desktop_close()`.
- **Session lifecycle** (red-team #4): the pid is re-resolved from the bundle id on every tool call; a dead or recycled pid ⇒ session invalidated, `_app` cleared, error JSON "app quit or restarted; call desktop_attach again" (never a raw AXError, never binding to an unrelated app that reused the pid). `-25202 InvalidUIElement` mid-call maps to the same path.
- `scripts/install_mcp.py`: replace the two module constants with `SERVERS: dict[str, ServerEntry]` (`server_name`, `entry_point`, `description`); CLI gains `--server {jev-browser,jev-desktop,all}` **defaulting to `jev-browser`** (red-team #6: desktop is opt-in); `--status` lists both; registry entries built per-server (keys `["mcpServers", <server_name>]`).
  - **Use-site checklist** (red-team #10 — `SERVER_NAME`/`ENTRY_POINT` appear in ~15 places; missing one registers `jev-desktop` as "jev-browser" and clobbers it): `server_argv` (:42), `Agent.json_keys` at import time (:203-272, 10 sites), codex status regex (:306), claude/commandcode CLI registration names (:324, :327), codex TOML header (:331), result strings (:336), `registration_status` (:299-309). Keep a `SERVER_NAME = "jev-browser"` module attribute for compatibility and update `tests/test_make_scripts.py:28`.
- **Install robustness** (red-team #14): per-agent/per-server `try/except` with a final summary (registered/failed/skipped); writes become atomic (temp file + rename); a malformed third-party config is reported, not fatal. "`--status`" belongs to `install_mcp.py`, not the MCP server (the server takes no such flag — `mcp_server.py:77-83` exits on unknown args).
- `Makefile`: `make install [agent]` registers **`jev-browser` only by default**; `make install-all [agent]` (or `--server all`) additionally opts into `jev-desktop`.
- `scripts/doctor.py`: (a) AX section on darwin — pyobjc importable, `AXIsProcessTrusted()` (with hint about System Settings → Privacy → Accessibility and the *host app* attribution), Chrome installed/running; (b) **MCP section loops agents × servers** — `check_mcp` currently hardcodes "jev-browser" (`doctor.py:166-174`), which would silently never report `jev-desktop` (red-team #11).

**Non-functional**
- No credentials in agent configs (existing rule — `server_argv` already handles `--env-file`).
- The desktop MCP server must start and serve tool listings with **no** Chrome running and **no** `.env` (no keys required).
- Writes to user configs are atomic and every registration failure is isolated and reported (red-team #14).

## Architecture

`desktop_mcp.py` mirrors `mcp_server.py` structure exactly (globals `_app`, `_config`-less). `install_mcp.py` keeps all helper functions; the `Agent` registry list-comprehension over `SERVERS` — each server × each agent = one registration. Backward compatibility: `tests/test_make_scripts.py` function-level contracts unchanged (`server_argv` gains an `entry_point` parameter with default `jev-mcp`).

## Related code

- Create: `jev_ultrafast/desktop_mcp.py`, `tests/test_desktop_mcp.py`
- Modify: `scripts/install_mcp.py`, `scripts/doctor.py`, `Makefile`, `pyproject.toml` (`jev-desktop = "jev_ultrafast.desktop_mcp:main"`), `tests/test_make_scripts.py` (adapt `server_argv` call)

## Implementation steps

1. `pyproject.toml`: add `jev-desktop` entry point.
2. `install_mcp.py`: introduce `ServerEntry` dataclass + `SERVERS` dict; walk the **use-site checklist** (functional requirements above) and thread `entry_point`/`server_name` through each; keep the `SERVER_NAME` compat attribute; add `--server` filtering (default `jev-browser`); atomic writes + per-agent isolation + summary.
3. `Makefile`: `install` → default server only; add `install-all`; `--status` output updates.
4. `desktop_mcp.py`: four tools; allowlist check in attach; single `_app` global; per-call pid re-resolution + dead-session mapping; attach resolution (bundle id) in a pure function for testability.
5. `doctor.py`: AX section (darwin-gated, informative not fatal when not trusted) + MCP section generalized to agents × servers.
6. Tests: registry idempotency with two servers (upsert of `jev-desktop` leaves `jev-browser` entry byte-identical); `--server` filter (default excludes desktop); **install isolation** (malformed config of agent #3 does not abort agents #4+; summary correct); **atomic write** (no partial file on injected write failure); allowlist (default Chrome-only, env override, error message names the env var); session lifecycle (pid gone / pid recycled ⇒ clean error + cleared session, never a raw AXError); MCP tools against a fake `DesktopApp` (observe/act/close happy + stale + not-attached); doctor MCP loop reports both servers.

## Success criteria

- `make install-dry` shows `jev-browser` for every detected agent; `make install-all --dry-run` additionally shows `jev-desktop`; running either twice changes nothing beyond the first write; `jev-desktop` is absent from every config unless explicitly opted in.
- A coding agent can register the desktop server explicitly and drive Chrome's menu bar with zero API keys.

## Test scope

- Mapped criteria → tests: two-server idempotency (critical); `--server` default + filter (parameterized jev-browser/jev-desktop/all/unknown); use-site sweep (codex TOML header, CLI names, status regex — one test asserting both servers appear under their own names); install isolation + summary; atomic write; allowlist (parameterized: default / env override / denied app); pid re-resolution paths; MCP observe/act/close happy + stale + not-attached; doctor agents × servers loop.
- Size: **L** (~14 test functions; justified: registry + lifecycle + allowlist each carry behavior not covered elsewhere).

## Risk assessment

- Codex TOML path with two servers → `upsert_toml_section` is per-section; add a test with both sections present (regression: header regex must not merge sections).
- Doctor false-fails on CI/Linux → every AX check darwin-gated and reported as `skipped`, never fatal.
