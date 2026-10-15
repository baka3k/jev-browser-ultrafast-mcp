# Browser Layer

Standalone browser control layer that external agents can drive.

## Usage

```python
from jev_ultrafast.browser import Browser

browser = Browser("https://example.com")
page = browser.observe()

# page contains:
# - url, title, text: page content
# - actions: list of interactive elements
# - fingerprint: hash for staleness detection

# Find an action to execute
action = next(a for a in page["actions"] if a["label"] == "Search")

# Execute it
browser.act(action, page, text="query")

# Observe again
new_page = browser.observe()

browser.close()
```

## Interface

### `Browser(url)`
Create a new browser session and navigate to URL.

### `browser.observe(screenshot=True) -> dict`
Read visible content and interactive controls. Returns:
- `url`, `title`, `text`: page state
- `actions`: list of `{id, kind, node, label, value, role, ...}`
- `fingerprint`: hash for staleness detection
- `screenshot`: base64 JPEG (if screenshot=True)

### `browser.act(action, page, text=None)`
Execute an action. Validates page freshness before execution.
- `action`: one item from `page["actions"]`
- `page`: the observation this action came from
- `text`: required for `kind="fill"` actions

### `browser.fresh(page, action=None) -> bool`
Check if page state is still valid. Optionally validate a specific action's target.

### `browser.close()`
Close the browser tab.

## Actions

Each action in `page["actions"]` has:
- `id`: unique identifier
- `kind`: `"click"`, `"fill"`, `"select"`, `"wait"`, `"scroll"`
- `node`: DOM node reference (integer)
- `label`: human-readable description
- `value`: current value (for inputs)
- `role`: ARIA role

## Staleness

The browser validates that the page hasn't changed before executing actions. If the page changes between observation and execution, `act()` raises `StalePage`. Catch this and re-observe:

```python
from jev_ultrafast.browser import StalePage

try:
    browser.act(action, page, text)
except StalePage:
    page = browser.observe()  # re-observe
    # retry with new page state
```

## Integration with external agents

External agents (Claude Code, Codex, etc.) can drive the browser by:

1. Calling `observe()` to get structured page state
2. Deciding which action to take
3. Calling `act()` to execute
4. Handling `StalePage` exceptions

The browser layer handles all CDP communication, DOM reading, and action execution. External agents only need to implement decision logic.
