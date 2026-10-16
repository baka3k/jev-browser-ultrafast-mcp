# Terminal layer

Drive interactive terminal programs — command in, verified output out. Built for
CLI agents like `claudex`: a terminal emulator (iTerm2) is a screen, not an API —
AX writes into its buffer are ignored, while a session we own accepts every
keystroke and echoes everything back.

```python
from jev_ultrafast.terminal import TerminalSession, TmuxSession

# headless private pty
with TerminalSession("/bin/zsh", ("-ic", "claudex")) as session:
    session.wait_for("You can type", timeout=120)   # the agent's greeting
    session.send("Fix the failing tests in tests/.")
    result = session.wait_for(r"all tests pass|error", timeout=600)

# same commands, but the session lives in tmux: attach in iTerm2 to watch
with TmuxSession(("/bin/zsh", "-ic", "claudex"), name="claudex") as session:
    ...
# watch it: tmux attach -t claudex   (or iTerm2's tmux integration)
```

## Interface (both backends)

| Call | Does |
| --- | --- |
| `send(text, press_enter=True)` | Write to the program; Enter appended unless disabled |
| `read_new()` | Consume output produced since the last read |
| `wait_for(pattern, timeout=15)` | Block until a regex appears in new output; `TimeoutError` carries the tail |
| `is_alive()` / `close()` | Process/session state; close is idempotent |

## Choosing a backend

| | `TerminalSession` (pty) | `TmuxSession` |
| --- | --- | --- |
| Dependencies | stdlib only | `tmux` on PATH |
| Visible | never | `tmux attach` in any terminal, incl. iTerm2 |
| Survives this process | no | yes |
| Output fidelity | raw terminal stream (escape sequences) | clean pane text (`capture-pane -p`) |

## Notes

- `send` writes bytes to the pty / tmux pane — it does **not** answer GUI prompts.
  Permission prompts (TCC, iTerm2 dialogs) still need a human or the AX layer.
- Output keeps the last `keep_last` characters (500k default); only already-read
  text is ever trimmed.
- Every task sent to a shell-running agent is a decision point: log your `send`
  calls like you log any other action.
