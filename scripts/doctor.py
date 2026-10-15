#!/usr/bin/env python3
"""Health check for the jev-ultrafast browser stack.

Usage: make doctor   (or: uv run python scripts/doctor.py --project <path>)

Reports the toolchain (uv, Python deps, entry points), the JS inspector files,
API key configuration, Chrome + browser-harness state, and which coding agents
have the jev-browser MCP server registered. Exit code is non-zero when a
critical check fails. API key values are never printed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import install_mcp  # noqa: E402

OK, WARN, FAIL = "ok", "warn", "fail"
ICONS = {OK: "✓", WARN: "!", FAIL: "✗"}
REPO_ROOT = Path(__file__).resolve().parent.parent

DEPS_PROBE = (
    "import sys; import jev_ultrafast, jev_ultrafast.demo, jev_ultrafast.mcp_server, mcp; print(sys.version.split()[0])"
)
JS_FILES = ["jev_ultrafast/static/app.js", "jev_ultrafast/browser/snapshot.js"]


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


def run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None


def chrome_installed() -> bool:
    candidates = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    if any(path.exists() for path in candidates):
        return True
    return any(shutil.which(name) for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"))


def check_toolchain(checks: list[Check], project: Path) -> str | None:
    uv = shutil.which("uv")
    if not uv:
        checks.append(Check("uv", FAIL, "not on PATH. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"))
        return None
    result = run([uv, "--version"])
    checks.append(Check("uv", OK, result.stdout.strip() if result else uv))

    result = run([uv, "run", "--no-sync", "python", "-c", DEPS_PROBE], cwd=project)
    if result is None:
        checks.append(Check("Python deps", FAIL, "could not run uv; check your installation"))
    elif result.returncode != 0:
        lines = result.stderr.strip().splitlines()
        detail = f"import failed — run 'make build'. {lines[-1]}" if lines else "import failed — run 'make build'"
        checks.append(Check("Python deps", FAIL, detail))
    else:
        modules = "jev_ultrafast, demo, mcp_server, mcp import"
        checks.append(Check("Python deps", OK, f"Python {result.stdout.strip()}; {modules}"))

    result = run([uv, "lock", "--check"], cwd=project)
    if result is None or result.returncode != 0:
        checks.append(Check("uv.lock", WARN, "lock file out of date — run 'uv lock' or 'make build'"))
    else:
        checks.append(Check("uv.lock", OK, "matches pyproject.toml"))

    entry_points = [project / ".venv" / "bin" / name for name in ("jev", "jev-mcp")]
    missing = [path.name for path in entry_points if not path.is_file()]
    if missing:
        checks.append(Check("Entry points", FAIL, f"missing in .venv/bin: {', '.join(missing)} — run 'make build'"))
    else:
        checks.append(Check("Entry points", OK, ".venv/bin/jev, .venv/bin/jev-mcp"))
    return uv


def check_js(checks: list[Check], project: Path) -> None:
    if not shutil.which("node"):
        checks.append(Check("Node.js", WARN, "not installed — skip JS syntax checks (needed for 'make build')"))
        return
    version = run(["node", "--version"])
    failed = []
    for rel in JS_FILES:
        result = run(["node", "--check", rel], cwd=project)
        if result is None or result.returncode != 0:
            failed.append(rel)
    if failed:
        checks.append(Check("JS syntax", FAIL, f"node --check failed: {', '.join(failed)}"))
    else:
        node_version = version.stdout.strip() if version else ""
        checks.append(Check("JS syntax", OK, f"node {node_version}; {len(JS_FILES)} files valid"))


def check_env(checks: list[Check], project: Path) -> None:
    env_path = project / ".env"
    if not env_path.is_file():
        checks.append(Check(".env", WARN, "missing — run 'cp .env.example .env' and add API keys"))
        return
    states = install_mcp.env_key_states(env_path)
    missing = [key for key, ok in states.items() if not ok]
    if missing:
        checks.append(Check(".env", WARN, f"empty or unset: {', '.join(missing)} (values are never printed)"))
    else:
        checks.append(Check(".env", OK, f"{len(states)} required keys set: {', '.join(states)}"))


def check_browser(checks: list[Check], project: Path, uv: str | None) -> None:
    if not chrome_installed():
        checks.append(Check("Chrome", FAIL, "Google Chrome not found — install it for the browser layer"))
    else:
        checks.append(Check("Chrome", OK, "installed"))

    if uv is None:
        return
    result = run([uv, "run", "--no-sync", "browser-harness", "doctor", "--json"], cwd=project, timeout=90)
    if result is None or result.returncode != 0:
        tail = (result.stderr or result.stdout or "").strip().splitlines()
        detail = tail[-1] if tail else "browser-harness doctor did not run"
        checks.append(Check("browser-harness", FAIL, f"{detail} — try 'uv run browser-harness --doctor'"))
        return
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        checks.append(Check("browser-harness", FAIL, f"unreadable doctor output: {result.stdout[:120]}"))
        return
    daemon = report.get("daemon", {})
    if not report.get("healthy"):
        checks.append(Check("browser-harness", FAIL, f"unhealthy: {json.dumps(report)}"))
        return
    if not daemon.get("alive"):
        checks.append(Check("browser-harness", WARN, f"v{report.get('version')} installed; daemon starts on first use"))
        return
    if not daemon.get("browser_ready"):
        detail = (
            f"v{report.get('version')} daemon alive, browser not ready — "
            "open Chrome or run 'uv run browser-harness --doctor'"
        )
        checks.append(Check("browser-harness", WARN, detail))
        return
    chrome_note = "Chrome running" if report.get("chrome_running") else "Chrome not running yet"
    checks.append(Check("browser-harness", OK, f"v{report.get('version')}; daemon alive, browser ready, {chrome_note}"))


def check_mcp(checks: list[Check]) -> None:
    registered = 0
    detected = 0
    for agent in install_mcp.AGENTS:
        state, path = install_mcp.registration_status(agent)
        if state == "registered":
            registered += 1
            checks.append(Check(f"MCP {agent.key}", OK, f"jev-browser registered in {path}"))
        elif state == "not registered":
            detected += 1
            hint = f"detected but not configured ({path}) — run 'make install {agent.key}'"
            checks.append(Check(f"MCP {agent.key}", WARN, hint))
    if registered == 0:
        checks.append(Check("MCP", WARN, "no agent has jev-browser registered — run 'make install'"))
    else:
        summary = f"{registered} agent(s) registered"
        if detected:
            summary += f", {detected} more detected without config"
        checks.append(Check("MCP", OK, summary))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the jev-ultrafast environment and browser stack.")
    parser.add_argument("--project", type=Path, default=REPO_ROOT, help="jev-ultrafast project directory")
    args = parser.parse_args(argv)
    project = args.project.resolve()

    checks: list[Check] = []
    uv = check_toolchain(checks, project)
    check_js(checks, project)
    check_env(checks, project)
    check_browser(checks, project, uv)
    check_mcp(checks)

    print(f"Jev Ultrafast doctor — {project}")
    for check in checks:
        print(f" {ICONS[check.status]} {check.name:16s} {check.detail}")
    counts = {status: sum(1 for c in checks if c.status == status) for status in (OK, WARN, FAIL)}
    verdict = "PASS" if counts[FAIL] == 0 else "FAIL"
    print(f"\n{verdict}: {counts[OK]} ok, {counts[WARN]} warnings, {counts[FAIL]} failures")
    if counts[FAIL] == 0:
        print("Deeper live check (opens a local browser, no model calls): uv run python scripts/check_guards.py")
    return 1 if counts[FAIL] else 0


if __name__ == "__main__":
    sys.exit(main())
