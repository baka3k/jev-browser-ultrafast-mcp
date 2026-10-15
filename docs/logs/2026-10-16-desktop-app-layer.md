# Desktop-app automation layer (macOS AX) + jev-desktop MCP — 2026-10-16

[inline:log-writer]

## Context

Plan `docs/plans/desktop-app-layer/plan.md` (hi-plan --full: research + red team 15/15 findings applied) asked for the jev indexed-element loop over desktop apps. Implemented end to end via hi-craft --full: phases 1–5, review, fix cycle, commit.

## Change

- `jev_ultrafast/desktop/`: `ax.py` — `AXBackend` Protocol (application/copy/set/perform/is_settable/action_names/same) + `PyobjcBackend` (guarded module-level import, error-code taxonomy: -25212/-25205 → absent, -25202 → `ElementGone`); `tree.py` — pure walker, node/depth budgets (3000/25), closed-menu rule, secure fields skipped, guards carry parent-path + position identity anchor; `app.py` — `DesktopApp.observe/fresh/act/close`, session-persistent element ids (retired, never reused), guard-before-mutation, fill verified by read-back.
- `jev_ultrafast/desktop_mcp.py`: `jev-desktop` MCP server; attach allowlist `JEV_DESKTOP_ALLOW` (default `com.google.Chrome` only); dead-app sessions clear themselves with an actionable error.
- `scripts/install_mcp.py`: generalized to a `SERVERS` registry (jev-browser default, jev-desktop opt-in); per-server json-keys/TOML derivation `json_keys[:-1] + [server_name]`; atomic writes (`write_atomic`); per-agent failure isolation (`install_selection`).
- `scripts/doctor.py`: Accessibility-permission + allowlist checks; MCP section loops agents × servers.
- `scripts/check_ax.py` + `make check-desktop`: live Chrome AX check, five-condition skip chain, mutations gated on the spike verdict.
- `pyproject.toml`: pyobjc deps marker-gated to darwin (`>=12,<13`), `jev-desktop` entry point.

## Impact

Coding agents can drive Chrome's chrome UI (menu bar, tabs, fields) through `desktop_attach/observe/act` with zero API keys; the browser layer is untouched. Risk: low-medium — an AX-trusted process can drive any app, mitigated by the allowlist and opt-in registration. Tests: 98 offline (no paid APIs, no model calls).

## Decision

- Focus-chain open-menu detection instead of the `AXMenus` app attribute: reviewer verified `AXMenus` is unsupported (-25205) on live Chrome 154, so the first implementation was dead code; a menu now counts as open when the app's focused element lives inside it (post-press state).
- Guards carry identity (parent path + position), not just attributes: prevents duplicate-label elements from passing freshness (red-team TOCTOU finding).
- jev-desktop registered only via explicit `make install-all` / `--server`: registering an AX-powered server into every agent config by default would silently widen the trust boundary.

## References

- plan: ./docs/plans/desktop-app-layer/plan.md
- review evidence: ./docs/plans/desktop-app-layer/red-team.md
- commit: 47c470f (branch feat/desktop-app-layer)
