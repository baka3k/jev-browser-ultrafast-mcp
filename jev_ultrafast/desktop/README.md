# Desktop layer

macOS twin of the browser layer: same loop, different observation source.

```python
from jev_ultrafast.desktop import DesktopApp

app = DesktopApp("com.google.Chrome")
page = app.observe()               # indexed element table (menu bar, tabs, fields, buttons)
action = page["actions"][0]
app.act(action, page)              # trusted AXPress / AXValue write, guard-checked first
app.close()
```

## Interface

| Call | Browser analogue | Notes |
| --- | --- | --- |
| `DesktopApp(bundle_id, backend=None)` | `Browser(url)` | backend injectable for tests; defaults to pyobjc (macOS only) |
| `observe()` | `Browser.observe()` | `{app, title, windows, text, actions, marker, fingerprint, omitted_actions}` |
| `fresh(page, action=None)` | `Browser.fresh()` | guard = attributes + parent path + position; marker only for DONE-style checks |
| `act(action, page, text=None)` | `Browser.act()` | kinds `click` (AXPress) / `fill` (AXValue write + read-back) / `wait`; raises `StaleState` on any change |
| `close()` | `Browser.close()` | releases cached refs; safe twice |

## Element table

Actions carry `{id, kind, label, role, value, node}` — the same shape as
`jev_ultrafast/browser/snapshot.js`, so `model.action_space()` and MCP formatting
consume them unchanged. Roles are mapped to the browser vocabulary
(`AXButton`→`button`, `AXTextField`→`textbox`, `AXMenuBarItem`→`menuitem`, ...).

- Kinds in v1: `click`, `fill`, `wait`. No `select`/scroll; no keyboard synthesis.
- Element ids (`e1`, `e2`, ...) persist across observations while the element lives and
  are retired, never reused, when it dies — matching is by full guard (attributes +
  parent path + position), so a recreated control in the same slot keeps its id and an
  id never silently starts pointing at a different control.
- Secure fields (`AXSecureTextField`) are never enumerated, like password inputs in the
  browser snapshot.
- Traversal is budgeted (3000 nodes / depth 25); closed `AXMenu` subtrees are never
  descended into; output caps at 250 actions with `omitted_actions` counted per skipped
  subtree.

## Scope (v1)

macOS only (pyobjc, marker-gated dependency). Every attach best-effort sets
`AXManualAccessibility` — the Electron opt-in — so Electron apps (VS Code, ZCode, …)
expose their full content tree, while Chrome and native apps refuse the attribute and
keep their native tree. Verified against Chrome chrome UI — menu bar, window controls —
per `docs/plans/desktop-app-layer/spike-activation.md`; browser web content stays with
the CDP layer. Windows UIA / Linux AT-SPI are a reserved seam (`AXBackend` Protocol),
deliberately unimplemented.
