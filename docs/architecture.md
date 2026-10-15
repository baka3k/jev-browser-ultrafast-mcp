# Architecture: Browser-Agent Separation

## Overview

Jev Ultrafast is split into independent layers:

1. **Browser Layer** (`jev_ultrafast/browser/`): Low-level browser control
2. **Agent Layer** (`jev_ultrafast/agent/`): Decision logic and model integration
3. **Desktop Layer** (`jev_ultrafast/desktop/`): macOS app control over the Accessibility API

## Browser Layer

Standalone browser controller that external agents can drive.

### Components
- `browser.py`: CDP connection, DOM observation, action execution
- `snapshot.js`: Atomic DOM reader, indexed controls
- `README.md`: Usage documentation

### Interface
```python
Browser(url) -> browser instance
browser.observe() -> page_state dict
browser.act(action, page, text) -> execute action
browser.fresh(page, action) -> bool
browser.close()
```

### Key features
- **Staleness detection**: Validates page hasn't changed before execution
- **Atomic observations**: Reads all controls in one CDP call
- **Freshness guards**: Rechecks target validity after text generation
- **Node identity**: Preserves actual DOM node references

## Desktop Layer

macOS twin of the browser layer: same element-table contract, Accessibility tree as the source.

### Components
- `ax.py`: `AXBackend` Protocol + pyobjc adapter (all platform imports live here, guarded)
- `tree.py`: Pure AX-tree walker -> indexed element table (budgeted traversal, closed-menu rule)
- `app.py`: `DesktopApp` facade (`observe/fresh/act/close`), session-persistent element ids
- `README.md`: Interface documentation

### Interface
```python
DesktopApp("com.google.Chrome", backend=None) -> app instance
app.observe() -> state dict (same action shape as the browser table)
app.act(action, page, text) -> trusted AXPress / AXValue write, guard-checked
app.fresh(page, action) -> bool (guard = attributes + parent path + position)
app.close()
```

### Key features
- **Contract parity**: `{id, kind, label, role, value, node}` actions feed `model.action_space()` and MCP formatting unchanged
- **Identity anchoring**: guards carry parent path + position; ids persist across observations for living elements and are never reused
- **Bounded traversal**: node/depth budgets; closed `AXMenu` subtrees are never descended into
- **Trusted execution**: `AXPress`/`AXValue` writes verified by read-back; secure fields never enumerated
- **Platform gating**: pyobjc is marker-gated to darwin; the rest of the package imports and tests on any OS

## Agent Layer

Decision logic that can be swapped for external agents.

### Components
- `agent.py`: Main loop (predict → act cycle)
- `model.py`: TypeSafe API integration, action space construction
- `questions.py`: Prompts and instructions for models

### Current implementation
Uses TypeSafe for operation/target selection and a text LLM for field values.

### Swapping the agent

Replace the agent layer with your own implementation:

```python
from jev_ultrafast.browser import Browser

browser = Browser(url)

while not done:
    page = browser.observe()
    
    # Your decision logic here
    action_id, text = your_agent.decide(page, goal, history)
    
    if action_id == "DONE":
        break
    
    action = next(a for a in page["actions"] if a["id"] == action_id)
    browser.act(action, page, text=text)
```

## Integration patterns

### Pattern 1: Claude Code as agent
```python
def decide_with_claude(page, goal, history):
    prompt = format_page_state(page) + format_goal(goal) + format_history(history)
    response = claude_code.prompt(prompt)
    return parse_action(response)
```

### Pattern 2: Codex as agent
```python
def decide_with_codex(page, goal, history):
    context = serialize(page, goal, history)
    response = codex.complete(context)
    return parse_action(response)
```

### Pattern 3: Custom LLM
```python
def decide_with_custom_llm(page, goal, history):
    messages = [
        {"role": "system", "content": "You control a browser..."},
        {"role": "user", "content": format_state(page, goal, history)},
    ]
    response = your_llm.chat(messages)
    return parse_action(response)
```

## Benefits

1. **Token efficiency**: External agents see structured element table, not raw DOM
2. **Flexibility**: Swap agents without changing browser control logic
3. **Testability**: Test browser and agent layers independently
4. **Reusability**: Browser layer can be used for non-agent tasks
5. **Simplicity**: Each layer has a single responsibility

## Migration guide

### Before (monolithic)
```python
from jev_ultrafast import Agent

agent = Agent(url, goal)
for state in agent.run():
    # TypeSafe makes all decisions
    pass
```

### After (external agent)
```python
from jev_ultrafast.browser import Browser

browser = Browser(url)
page = browser.observe()

while True:
    # Your agent decides
    action_id, text = your_agent.decide(page, goal, history)
    
    if action_id == "DONE":
        break
    
    action = next(a for a in page["actions"] if a["id"] == action_id)
    browser.act(action, page, text=text)
    page = browser.observe()
```

## Examples

- `examples/external_agent.py`: Template for external agent integration
- `examples/run.py`: Original TypeSafe agent (still works)
- `examples/flights.py`: Google Flights demo with TypeSafe

## Testing

Browser, desktop, and agent layers are tested independently:
- `tests/test_agent.py`: Agent logic, model integration, action selection
- `tests/test_desktop.py`, `tests/test_desktop_actions.py`, `tests/test_desktop_mcp.py`: AX tree walking, guard discipline, MCP tools (fake backend, offline)
- Browser tests: DOM reading, action execution, staleness detection
- Live checks stay out of pytest: `scripts/check_guards.py` (browser), `scripts/check_ax.py` (desktop, skips when Chrome/Accessibility is unavailable)
