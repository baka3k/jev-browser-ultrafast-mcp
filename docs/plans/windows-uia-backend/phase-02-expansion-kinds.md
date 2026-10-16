# Phase 02 — Expansion action kinds: select / scroll / keyboard (Windows)

Priority: P2 · Status: Pending · Effort: ~6h · Test scope: M (see bottom)

## Context

- Walker role→kind mapping: `jev_ultrafast/desktop/tree.py` (`ROLE_MAP`, `EDITABLE_ROLES`, action emission at `:144`, `:168-189`).
- Execution paths: `jev_ultrafast/desktop/app.py:95-117` (`act`), pressability `_pressable` `:119-123`.
- **Existing select machinery**: `jev_ultrafast/agent/model.py:155` already maps `select → SELECT` with option-grouping (`:167-180`); the browser layer already emits per-option `select` actions (`browser/snapshot.js:69-71`).
- Scope mode EXPANSION (user-selected 2026-10-16); research: [research-uia-ecosystem.md](./research-uia-ecosystem.md) §2, §5; red-team findings 1, 2, 4, 5 applied below.

## Overview

Add three action kinds beyond `click`/`fill`/`wait`, emitted **only when the backend reports capability** so the macOS loop stays click/fill/wait: `select` (list items, combo boxes — **reusing the model's existing select machinery**, not new vocabulary), `scroll` (scrollable containers), and `type` (**closed key-sequence synthesis** — Enter/Tab/Escape/arrows — not free text). Windows-first; macOS parity only where free (AXPick for select); macOS scroll/keyboard explicitly deferred.

## Key decisions (red-team adjudicated)

- **`select` is not new to the model**: `model.action_space` already knows it; unknown kinds already become controls (`model.py:158-160`). The work here is the **desktop emission shape**: per-item actions (each list item its own element, executed directly via SelectionItem.Select). Option-grouping like the browser is rejected for desktop — it would produce degenerate single-option groups (`"1:1"`, `"2:1"` targets) with no read-back benefit. Document this divergence in `model` docs.
- **`type` carries a key sequence, never free text.** Free text already has `fill` (SetValue + read-back verification); SendInput free text would duplicate it with worse guarantees (no read-back) and would drag the TYPE_TEXT text-helper + cache rule into a kind that doesn't need it. `type` accepts a **closed vocabulary** of key names (`Enter`, `Tab`, `Escape`, `ArrowUp/Down/Left/Right`) passed in the action's `text` field; anything outside the vocabulary is refused before execution. Desktop actions stay MCP-path-only — the Python `Agent` loop genericization remains deferred (predecessor plan), so `agent/agent.py:106-115` is untouched.
- **Foreground predicate is exact**: before SendInput, `GetForegroundWindow` → `GetWindowThreadProcessId` must land in the **PID set resolved from the allowlisted entry** (not just "some window of some process"). SetFocus counts as part of the single logged attempt: a refused `type` reports that focus was set, and is never retried (repo rule).

## Key insights from research

- SelectionItem.Select is spec-confirmed for VB6 list items through the MSAA bridge; combos via ExpandCollapse.
- **Scroll is NOT in the bridge's pattern fallback** (Invoke/ExpandCollapse/Toggle only) → `scroll` will exist for native-UIA content (ScrollPattern) but likely never for VB6/MSAA content. Scope the promise accordingly; spike (Phase 4) records the verdict.
- SendInput lands in the foreground thread's queue — hence the exact predicate above.

## Requirements

**Functional**
- Capability-gated emission: walker emits `select` for list-item/combobox roles and `scroll` for scrollable containers **iff** a new optional backend capability probe reports support; `type` emitted on Windows only. macOS keeps click/fill/wait plus `select` only where the AX backend already reports `AXPick` in `action_names` (no behavior change today, regression-guarded).
- `UiaBackend` support: `select` → SelectionItem.Select (ExpandCollapse.Expand fallback for combos); `scroll` → ScrollPattern scroll by configurable amount with direction; `type` → SetFocus + foreground predicate + SendInput(KEYEVENTF_UNICODE) for the key sequence, refusing outside the closed vocabulary or on foreground mismatch.
- AX-action names: `"AXPick"` for select (already in the Protocol docstring); the scroll action name decided in implementation and documented. Keyboard is an app-level platform capability flag from the backend, not a per-element AX action.
- `model.action_space` / MCP docstrings: only the kind list and descriptions change — `select` needs no model change; the walker-emission shape divergence is documented. Kind vocabulary stays single-source (one module, consumed by walker + model + MCP), one consistency test.
- All three kinds flow through the existing guard-before-mutation path — **no new mutation path bypasses `fresh()`**; stale refusals get actionable text.

**Non-functional**
- Keyboard synthesis is allowlist-gated like everything else; the foreground PID predicate (above) closes the collision-typing hole from red-team finding 4. README security note updated in Phase 4.

## Related code

- Modify: `jev_ultrafast/desktop/uia.py` (patterns + SendInput helper), `jev_ultrafast/desktop/tree.py` (capability-gated emission, per-item select shape), `jev_ultrafast/desktop/app.py` (`act` branches + platform capability flag), `jev_ultrafast/desktop_mcp.py` (docstrings).
- Untouched: `agent/model.py` semantics for existing kinds (kind-list addition only), `agent/agent.py` (desktop stays MCP-path-only).
- Keep compatible: `tests/test_desktop.py` FakeBackend gains the optional capability methods with macOS-safe defaults.

## Implementation steps

1. Protocol extension: optional capability probe with default-off implementations in `PyobjcBackend`/fakes (one shape, documented).
2. `UiaBackend`: SelectionItem/ExpandCollapse/ScrollPattern wiring; SendInput helper with the exact foreground predicate and closed key vocabulary.
3. Walker emission rules per role × capability, per-item select shape; `omitted_actions` accounting still applies (tested).
4. `app.py` execution branches behind the existing `fresh()` gate; refusal messages actionable ("foreground lost — refocus and observe again").
5. Kind vocabulary single-source + MCP docstrings; document the per-item select divergence from browser option-grouping.
6. Tests per the budget below.

## Success criteria

- On the fake backend: kinds appear only when capability is on; every mutation is guard-checked — one test per new kind proves a stale decision refuses before mutation; refused sends raise `StaleState`-family errors with actionable text, never retried.
- macOS suite green with zero behavior change; new kinds provably absent on macOS fakes.
- `type` refuses any key sequence outside the closed vocabulary before touching the backend.

## Risk assessment

- **Scroll never appears on VB6 content** (research: bridge fallback lacks Scroll) → promise scoped to native UIA; spike records it; do not fake scroll with clicks.
- **SendInput AV/UX flags** (`inferred`, community-only) → foreground predicate + allowlist + docs; not mitigated further.
- **Closed-menu pruning on Windows** (`unknown`, red-team finding 3 — load-bearing) → spike question + contingency: a backend capability flag that bypasses `MENU_ROLES` pruning on Windows if Win32 menus don't match the focused-element open-indicator model; decided from spike evidence, not speculation.
- **Vocabulary drift** between walker/model/MCP → single-source kind list; one consistency test.
- Keyboard could type into the wrong app on a race → PID-set foreground re-check immediately before send; mismatch refuses (and the attempt, including SetFocus, is logged).

## Test scope (per test-budget)

Mapped behaviors → tests: capability gating matrix (2: walker emission on/off), select emission shape per-item (1), select execution (2: item + combo fallback), scroll execution (2: native success, pattern-absent refusal), type (3: vocabulary-refused, foreground-refused, success), stale-guard refusal before mutation per new kind (1 parameterized over 3 kinds), macOS regression guard (1), kind-consistency walker/model/MCP (1), omitted_actions accounting with new kinds (1). **≈ 14 test functions — size M; justified: the stale-guard parameterized test covers 3 kinds in 1 function, and 2 functions (regression, consistency) are red-team-mapped requirements that had no test.**
