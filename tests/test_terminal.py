"""Offline contracts for the terminal driving layer. Local processes only, no paid APIs."""

import os
import shutil
import subprocess
import uuid

import pytest

from jev_ultrafast.terminal import TerminalError, TerminalSession, TmuxSession


def wait_for_count(session, marker, count, timeout=5.0):
    """Poll read_new until `marker` appears `count` times in total (echo + output)."""
    import time

    deadline = time.monotonic() + timeout
    seen = ""
    while time.monotonic() < deadline:
        seen += session.read_new()
        if seen.count(marker) >= count:
            return seen
        time.sleep(0.05)
    raise AssertionError(f"{marker!r} appeared {seen.count(marker)} times, expected {count}: {seen[-200:]!r}")


# --- pty backend ---------------------------------------------------------------


def test_command_output_is_verified_end_to_end():
    with TerminalSession("/bin/sh") as session:
        session.send("echo MARK_$((40+2))")
        output = session.wait_for("MARK_42")
        assert "MARK_42" in output


def test_press_enter_false_holds_the_line():
    with TerminalSession("/bin/cat", ()) as session:  # no args: cat echoes lines back
        session.send("MARK_HOLD", press_enter=False)
        echoed = wait_for_count(session, "MARK_HOLD", 1)  # the tty echoed the typed chars
        assert echoed.count("MARK_HOLD") == 1  # cat has not received the line yet
        session.send("", press_enter=True)  # newline hands the line to cat
        produced = wait_for_count(session, "MARK_HOLD", 1)  # fresh output: cat's own echo
        assert produced.count("MARK_HOLD") == 1


def test_wait_for_timeout_carries_the_tail():
    with TerminalSession("/bin/sleep", ("30",)) as session:
        with pytest.raises(TimeoutError, match="NEVER_GOING"):
            session.wait_for("NEVER_GOING_TO_APPEAR", timeout=0.6)


def test_process_exit_reports_and_flushes():
    with TerminalSession("/bin/sh", ("-c", "echo FLUSH_MARKER")) as session:
        output = session.wait_for("FLUSH_MARKER")
        assert "FLUSH_MARKER" in output
        deadline = 50
        while session.is_alive() and deadline:
            import time

            time.sleep(0.1)
            deadline -= 1
        assert not session.is_alive()
        assert "FLUSH_MARKER" in session.read_new() + output


def test_close_is_idempotent_and_context_manager_closes():
    with TerminalSession("/bin/sleep", ("30",)) as session:
        assert session.is_alive()
    session.close()  # second close must not raise
    assert not session.is_alive()


def test_window_size_reaches_the_program():
    with TerminalSession("/bin/sh", cols=120, rows=30) as session:
        session.send("stty size")
        assert session.wait_for(r"30 120", timeout=5)


def test_env_and_cwd_are_respected(tmp_path):
    env = {**os.environ, "JEV_TEST_VAR": "jev-env-marker"}
    with TerminalSession("/bin/sh", cwd=tmp_path, env=env) as session:
        session.send('echo "$JEV_TEST_VAR" "$(pwd)"')
        output = session.wait_for("jev-env-marker")
        assert str(tmp_path) in output


def test_output_memory_is_bounded_by_keep_last():
    with TerminalSession("/bin/sh", keep_last=200) as session:
        session.send("awk 'BEGIN{for(i=1;i<=500;i++)print i}'")
        session.wait_for(r"\r\n500\r\n", timeout=5)
        session.read_new()
        assert len(session._buffer) <= 400  # trimmed tail only; unbounded growth is the bug


def test_unicode_round_trips():
    with TerminalSession("/bin/sh") as session:
        session.send("echo héllo→ok")
        assert "héllo→ok" in session.wait_for("héllo→ok")


# --- tmux backend --------------------------------------------------------------


pytestmark_tmux = pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed")


@pytest.fixture
def tmux_cleanup():
    names = []

    def register(session):
        names.append(session.name)
        return session

    yield register
    for name in names:
        subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True, timeout=10)


@pytestmark_tmux
def test_tmux_command_output_is_verified(tmux_cleanup):
    session = tmux_cleanup(TmuxSession(("/bin/sh",)))
    session.send("echo TMUX_MARK_$((40+2))")
    assert "TMUX_MARK_42" in session.wait_for("TMUX_MARK_42")


@pytestmark_tmux
def test_tmux_named_session_survives_the_driver(tmux_cleanup):
    name = f"jev-test-{uuid.uuid4().hex[:8]}"
    session = tmux_cleanup(TmuxSession(("/bin/sleep", "30"), name=name))
    assert session.is_alive()
    listed = subprocess.run(["tmux", "list-sessions"], capture_output=True, text=True, timeout=10).stdout
    assert name in listed  # it exists outside this process
    session.close()
    assert not session.is_alive()


@pytestmark_tmux
def test_tmux_duplicate_name_raises():
    name = f"jev-test-{uuid.uuid4().hex[:8]}"
    first = TmuxSession(("/bin/sleep", "30"), name=name)
    try:
        with pytest.raises(TerminalError, match="new-session failed"):
            TmuxSession(("/bin/sleep", "30"), name=name)
    finally:
        first.close()


@pytestmark_tmux
def test_tmux_close_is_idempotent(tmux_cleanup):
    session = tmux_cleanup(TmuxSession(("/bin/sleep", "30")))
    session.close()
    session.close()
    assert not session.is_alive()
