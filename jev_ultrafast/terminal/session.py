"""Drive interactive terminal programs — command in, verified output out.

Two backends behind one small interface:

- `TerminalSession` owns a private pseudo-terminal (stdlib `pty`): headless,
  zero dependencies, nothing visible.
- `TmuxSession` runs the program inside a named tmux session: `send` becomes
  `tmux send-keys`, output comes from `capture-pane`, and the session survives
  this process — attach it in iTerm2 (`tmux attach -t <name>`) to watch.

This is the layer for driving CLI agents like `claudex`: a terminal emulator
(iTerm2) is a screen, not an API — AX writes into its buffer are ignored, while
a session we own accepts every keystroke and echoes everything back for
independent verification.
"""

import codecs
import fcntl
import os
import pty
import re
import select
import shlex
import struct
import subprocess
import termios
import time
import uuid


class TerminalError(RuntimeError):
    """A terminal session could not be started or driven."""


class _SessionBase:
    """Shared command semantics; subclasses push output and write input."""

    def __init__(self, keep_last: int = 500_000):
        self._buffer = ""  # everything produced so far (tail-trimmed to keep_last)
        self._consumed = 0  # offset of what read_new has already handed out
        self.keep_last = keep_last

    # --- backend surface ------------------------------------------------------

    def _push(self) -> None:
        """Pull newly produced output into the buffer."""
        raise NotImplementedError

    def _write(self, text: str) -> None:
        raise NotImplementedError

    def _press_enter(self) -> None:
        raise NotImplementedError

    def _alive(self) -> bool:
        raise NotImplementedError

    def _shutdown(self) -> None:
        raise NotImplementedError

    # --- shared semantics -----------------------------------------------------

    def send(self, text: str, *, press_enter: bool = True) -> None:
        """Write text to the program; append Enter unless press_enter is False."""
        self._push()
        self._write(text)
        if press_enter:
            self._press_enter()

    def read_new(self) -> str:
        """Consume output produced since the last read."""
        self._push()
        new = self._buffer[self._consumed:]
        self._consumed = len(self._buffer)
        if self._consumed > self.keep_last:  # drop only what was already consumed
            cut = self._consumed - self.keep_last
            self._buffer = self._buffer[cut:]
            self._consumed -= cut
        return new

    def wait_for(self, pattern: str, timeout: float = 15.0) -> str:
        """Block until `pattern` (regex) appears in new output; return that output.

        Raises TimeoutError carrying the last output when the deadline passes.
        """
        compiled = re.compile(pattern)
        deadline = time.monotonic() + timeout
        collected: list[str] = []
        while True:
            new = self.read_new()
            if new:
                collected.append(new)
                if compiled.search(new):
                    return "".join(collected)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                tail = "".join(collected)[-400:]
                raise TimeoutError(f"{pattern!r} not found within {timeout}s. Last output: {tail!r}")
            time.sleep(min(0.1, remaining))

    def is_alive(self) -> bool:
        return self._alive()

    def close(self) -> None:
        self._shutdown()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class TerminalSession(_SessionBase):
    """A program running in a pseudo-terminal we own. Stdlib only, headless."""

    def __init__(self, command="/bin/zsh", args=("-i",), *, cwd=None, env=None,
                 cols=120, rows=30, keep_last=500_000):
        super().__init__(keep_last=keep_last)
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._pending = b""
        self._closed = False
        master, slave = pty.openpty()
        try:
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
            self._proc = subprocess.Popen(
                [command, *args], stdin=slave, stdout=slave, stderr=slave,
                cwd=cwd, env=env, close_fds=True,
            )
        except OSError:
            os.close(master)
            os.close(slave)
            raise
        os.close(slave)
        self._master = master

    def _push(self) -> None:
        while True:
            try:
                ready, _, _ = select.select([self._master], [], [], 0)
            except OSError:
                return  # master closed
            if not ready:
                return
            try:
                chunk = os.read(self._master, 65536)
            except OSError:
                return  # EIO: the child closed its side
            if not chunk:
                return
            self._pending += chunk
            try:
                text = self._decoder.decode(self._pending)
                self._pending = b""
            except UnicodeDecodeError:  # a split multibyte sequence: keep the tail
                text = self._decoder.decode(self._pending[:-4], "replace")
                self._pending = self._pending[-4:]
            self._buffer += text
            self._consumed = self._consumed  # read_new tracks consumption

    def _write(self, text: str) -> None:
        os.write(self._master, text.encode("utf-8"))

    def _press_enter(self) -> None:
        os.write(self._master, b"\r")

    def _alive(self) -> bool:
        return self._proc.poll() is None

    def _shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=3)
        os.close(self._master)


class TmuxSession(_SessionBase):
    """A program inside a named tmux session — attachable in iTerm2, survives us.

    send  → `tmux send-keys`   output → `tmux capture-pane`
    Attach with `tmux attach -t <name>` (or iTerm2's tmux integration) to watch.
    """

    def __init__(self, command=("/bin/zsh",), *, name=None, cwd=None, cols=200, rows=50,
                 timeout=10.0, keep_last=500_000):
        super().__init__(keep_last=keep_last)
        self.name = name or f"jev-{uuid.uuid4().hex[:8]}"
        self._snapshot = ""
        joined = " ".join(shlex.quote(part) for part in command)
        result = subprocess.run(
            ["tmux", "new-session", "-d", "-s", self.name, "-x", str(cols), "-y", str(rows), joined],
            capture_output=True, text=True, cwd=cwd, timeout=timeout,
        )
        if result.returncode != 0:
            raise TerminalError(f"tmux new-session failed: {result.stderr.strip()}")

    def _push(self) -> None:
        result = subprocess.run(
            ["tmux", "capture-pane", "-p", "-S", "-", "-t", self.name],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return  # session ended; is_alive/close report it
        content = result.stdout
        if content.startswith(self._snapshot):
            new = content[len(self._snapshot):]
        else:  # the pane scrolled or redrew: hand the caller the whole pane
            new = content
        self._snapshot = content
        self._buffer += new

    def _write(self, text: str) -> None:
        result = subprocess.run(["tmux", "send-keys", "-t", self.name, "-l", text],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise TerminalError(f"tmux send-keys failed: {result.stderr.strip()}")

    def _press_enter(self) -> None:
        result = subprocess.run(["tmux", "send-keys", "-t", self.name, "Enter"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            raise TerminalError(f"tmux Enter failed: {result.stderr.strip()}")

    def _alive(self) -> bool:
        result = subprocess.run(["tmux", "has-session", "-t", self.name],
                                capture_output=True, text=True, timeout=10)
        return result.returncode == 0

    def _shutdown(self) -> None:
        if self._alive():
            subprocess.run(["tmux", "kill-session", "-t", self.name],
                           capture_output=True, text=True, timeout=10)
