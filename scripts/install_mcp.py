#!/usr/bin/env python3
"""Register the Jev browser MCP server (jev-mcp) with coding agents.

Usage:
    uv run python scripts/install_mcp.py --agent all
    uv run python scripts/install_mcp.py --agent cursor
    uv run python scripts/install_mcp.py --status

The registration is idempotent: re-running replaces the `jev-browser` entry in
place and leaves every other configured server untouched. Credentials are never
written into agent configs; the server command loads them from the project's
.env file via `uv --directory <project> run --env-file <project>/.env jev-mcp`.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

SERVER_NAME = "jev-browser"
ENTRY_POINT = "jev-mcp"
REPO_ROOT = Path(__file__).resolve().parent.parent


# --- shared helpers -----------------------------------------------------------


def find_uv() -> str:
    uv = shutil.which("uv")
    if not uv:
        sys.exit("uv is required but was not found on PATH. Install: curl -LsSf https://astral.sh/uv/install.sh | sh")
    return uv


def server_argv(project: Path, uv: str) -> list[str]:
    """Full command an agent should spawn: absolute, no cwd or env setup needed."""
    argv = [uv, "--directory", str(project), "run"]
    env_file = project / ".env"
    if env_file.is_file():
        argv += ["--env-file", str(env_file)]
    argv.append(ENTRY_POINT)
    return argv


def strip_jsonc(text: str) -> str:
    """Remove // and /* */ comments outside strings (Cursor configs are JSONC)."""
    out: list[str] = []
    in_string = False
    escaped = False
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
        elif ch == "/" and text[i : i + 2] == "//":
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        elif ch == "/" and text[i : i + 2] == "/*":
            i = text.find("*/", i + 2)
            i = len(text) if i == -1 else i + 2
            continue
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def load_json_file(path: Path) -> dict:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        cleaned = re.sub(r",\s*([}\]])", r"\1", strip_jsonc(text))
        data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def upsert_json_path(path: Path, keys: list[str], entry: dict) -> str:
    """Set data[keys...] = entry, preserving everything else. Returns created|updated."""
    data = load_json_file(path)
    node = data
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    action = "updated" if isinstance(node.get(keys[-1]), dict) else "created"
    node[keys[-1]] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return action


def json_entry_present(path: Path, keys: list[str]) -> bool:
    try:
        node: dict = load_json_file(path)
    except (json.JSONDecodeError, ValueError):
        return False
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            return False
        node = child
    return isinstance(node.get(keys[-1]), dict)


def upsert_toml_section(path: Path, header: str, body_lines: list[str]) -> str:
    """Replace or append one [header] section. Returns created|updated."""
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    block = "\n".join([f"[{header}]", *body_lines]) + "\n"
    pattern = re.compile(rf"(?ms)^\[{re.escape(header)}\][ \t]*\n.*?(?=^\[|\Z)")
    if pattern.search(text):
        text = pattern.sub(lambda _: block, text, count=1)
        action = "updated"
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        if text:
            block = "\n" + block
        text += block
        action = "created"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return action


def run_cli(cmd: list[str]) -> bool:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def env_key_states(env_path: Path) -> dict[str, bool]:
    """Which required API keys are set (non-empty). Values are never returned."""
    states = {"TYPESAFE_API_KEY": False, "TEXT_MODEL_API_KEY": False}
    if not env_path.is_file():
        return states
    for line in env_path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() in states and value.strip():
            states[key.strip()] = True
    return states


# --- agent registry -----------------------------------------------------------


def default_entry(argv: list[str], project: Path) -> dict:
    return {"command": argv[0], "args": argv[1:]}


def stdio_entry(argv: list[str], project: Path) -> dict:
    return {"type": "stdio", "command": argv[0], "args": argv[1:]}


@dataclass
class Agent:
    key: str
    label: str
    json_keys: list[str]  # nested path to the servers map inside the config file
    config_path: Callable[[], Path]
    installed: Callable[[], bool]
    aliases: tuple[str, ...] = ()
    entry: Callable[[list[str], Path], dict] = default_entry


def _home(*parts: str) -> Path:
    return Path.home().joinpath(*parts)


AGENTS: list[Agent] = [
    Agent(
        key="claude",
        label="Claude Code",
        json_keys=["mcpServers", SERVER_NAME],
        config_path=lambda: _home(".claude.json"),
        installed=lambda: bool(shutil.which("claude")) or _home(".claude.json").is_file(),
        entry=stdio_entry,
    ),
    Agent(
        key="codex",
        label="OpenAI Codex CLI",
        json_keys=["mcpServers", SERVER_NAME],  # TOML; keys unused for status
        config_path=lambda: _home(".codex", "config.toml"),
        installed=lambda: bool(shutil.which("codex")) or _home(".codex").is_dir(),
    ),
    Agent(
        key="commandcode",
        label="Command Code",
        aliases=("cmd", "cmdcode"),
        json_keys=["mcpServers", SERVER_NAME],
        config_path=lambda: _home(".commandcode", "mcp.json"),
        installed=lambda: bool(shutil.which("cmd")) or _home(".commandcode").is_dir(),
        entry=lambda argv, project: {"transport": "stdio", "command": argv[0], "args": argv[1:]},
    ),
    Agent(
        key="vscode",
        label="VS Code",
        aliases=("code", "vs-code", "vs"),
        json_keys=["servers", SERVER_NAME],
        config_path=lambda: _vscode_mcp_json(),
        installed=lambda: bool(shutil.which("code")) or _vscode_mcp_json().parent.is_dir(),
    ),
    Agent(
        key="cursor",
        label="Cursor",
        json_keys=["mcpServers", SERVER_NAME],
        config_path=lambda: _home(".cursor", "mcp.json"),
        installed=lambda: bool(shutil.which("cursor") or shutil.which("cursor-agent")) or _home(".cursor").is_dir(),
    ),
    Agent(
        key="qwen",
        label="Qwen Code",
        json_keys=["mcpServers", SERVER_NAME],
        config_path=lambda: _home(".qwen", "settings.json"),
        installed=lambda: bool(shutil.which("qwen")) or _home(".qwen").is_dir(),
    ),
    Agent(
        key="ayg",
        label="Google Antigravity",
        aliases=("agy", "agv", "anti", "antigravity"),
        json_keys=["mcpServers", SERVER_NAME],
        config_path=lambda: _home(".gemini", "config", "mcp_config.json"),
        installed=lambda: _home(".gemini", "config").is_dir() or bool(shutil.which("agd")),
    ),
    Agent(
        key="gemini",
        label="Gemini CLI",
        json_keys=["mcpServers", SERVER_NAME],
        config_path=lambda: _home(".gemini", "settings.json"),
        installed=lambda: bool(shutil.which("gemini")) or _home(".gemini").is_dir(),
    ),
    Agent(
        key="opencode",
        label="OpenCode",
        json_keys=["mcp", SERVER_NAME],
        config_path=lambda: _home(".config", "opencode", "opencode.json"),
        installed=lambda: bool(shutil.which("opencode")) or _home(".config", "opencode").is_dir(),
        entry=lambda argv, project: {"type": "local", "command": argv, "enabled": True},
    ),
    Agent(
        key="zcode",
        label="ZCode",
        json_keys=["mcp", "servers", SERVER_NAME],
        config_path=lambda: _home(".zcode", "cli", "config.json"),
        installed=lambda: _home(".zcode", "cli").is_dir(),
        entry=lambda argv, project: {"type": "stdio", "command": argv[0], "args": argv[1:], "cwd": str(project)},
    ),
]

BY_KEY = {agent.key: agent for agent in AGENTS}
for agent in AGENTS:
    for alias in agent.aliases:
        BY_KEY[alias] = agent


def _vscode_mcp_json() -> Path:
    if sys.platform == "darwin":
        return _home("Library", "Application Support", "Code", "User", "mcp.json")
    return _home(".config", "Code", "User", "mcp.json")


def resolve_agent(name: str) -> Agent:
    agent = BY_KEY.get(name.strip().lower())
    if agent is None:
        supported = ", ".join(a.key for a in AGENTS)
        sys.exit(f"Unknown agent '{name}'. Supported: {supported}, all")
    return agent


def registration_status(agent: Agent) -> tuple[str, Path]:
    """Return (registered | not registered | not installed, config path)."""
    path = agent.config_path()
    if not agent.installed() and not path.is_file():
        return "not installed", path
    if agent.key == "codex":
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
        registered = bool(re.search(rf'^\[mcp_servers\."?{re.escape(SERVER_NAME)}"?\]', text, re.M))
    else:
        registered = json_entry_present(path, agent.json_keys)
    return ("registered" if registered else "not registered"), path


# --- installers ---------------------------------------------------------------


def install_agent(agent: Agent, project: Path, uv: str, dry_run: bool) -> str:
    argv = server_argv(project, uv)
    target = agent.config_path()
    planned = f"  {agent.label} [{agent.key}] -> {target}"

    if dry_run:
        return planned + f"\n    command: {' '.join(argv)}"

    if agent.key == "claude":
        if shutil.which("claude") and run_cli(["claude", "mcp", "add", "--scope", "user", SERVER_NAME, "--", *argv]):
            return planned + "\n    registered via claude mcp add (user scope)"
    elif agent.key == "commandcode":
        if shutil.which("cmd") and run_cli(["cmd", "mcp", "add", "--scope", "user", SERVER_NAME, "--", *argv]):
            return planned + "\n    registered via cmd mcp add (user scope)"

    if agent.key == "codex":
        header = f'mcp_servers."{SERVER_NAME}"'
        body = [f"command = {json.dumps(argv[0])}", f"args = {json.dumps(argv[1:])}"]
        action = upsert_toml_section(target, header, body)
    else:
        action = upsert_json_path(target, agent.json_keys, agent.entry(argv, project))
    return planned + f"\n    {action} {SERVER_NAME} entry"


# --- entry point --------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Register the jev-browser MCP server with coding agents.")
    parser.add_argument("--agent", default="all", help="agent key (see --list) or 'all' (default: all)")
    parser.add_argument("--project", type=Path, default=REPO_ROOT, help="jev-ultrafast project directory")
    parser.add_argument("--dry-run", action="store_true", help="show what would be written without changing anything")
    parser.add_argument("--status", action="store_true", help="only show current registration status")
    parser.add_argument("--list", action="store_true", help="list supported agents and exit")
    args = parser.parse_args(argv)

    if args.list:
        for agent in AGENTS:
            aliases = f" (aliases: {', '.join(agent.aliases)})" if agent.aliases else ""
            print(f"{agent.key:12s} {agent.label}{aliases}")
        return 0

    project = args.project.resolve()
    if args.status:
        for agent in AGENTS:
            state, path = registration_status(agent)
            print(f"{agent.key:12s} {state:15s} {path if state != 'not installed' else '-'}")
        return 0

    uv = find_uv()
    missing = [key for key, ok in env_key_states(project / ".env").items() if not ok]
    if missing:
        print(f"warning: {', '.join(missing)} empty or missing in {project / '.env'}; "
              f"the MCP server starts but API calls fail until configured.")

    selected = AGENTS if args.agent.strip().lower() == "all" else [resolve_agent(args.agent)]
    for agent in selected:
        if args.agent.strip().lower() == "all" and not agent.installed() and not agent.config_path().is_file():
            print(f"- {agent.label} [{agent.key}]: not detected, skipped")
            continue
        print(install_agent(agent, project, uv, args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
