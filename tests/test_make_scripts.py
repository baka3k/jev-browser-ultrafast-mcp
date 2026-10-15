"""Offline contracts for the Makefile helper scripts. No paid APIs, no user config writes."""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


install_mcp = load_script("install_mcp")


def agent_with(config_path: Path, installed: bool = True) -> install_mcp.Agent:
    return install_mcp.Agent(
        key="testagent",
        label="Test Agent",
        json_keys=["mcpServers", install_mcp.SERVER_NAME],
        config_path=lambda: config_path,
        installed=lambda: installed,
    )


def test_server_argv_loads_env_file_only_when_present(tmp_path):
    uv = "/usr/local/bin/uv"
    (tmp_path / ".env").write_text("TYPESAFE_API_KEY=x\n")
    with_env = install_mcp.server_argv(tmp_path, uv)
    assert "--env-file" in with_env and with_env[-1] == "jev-mcp"
    assert with_env[with_env.index("--directory") + 1] == str(tmp_path)

    plain = install_mcp.server_argv(tmp_path / "no-env", uv)
    assert "--env-file" not in plain


def test_resolve_agent_aliases_and_unknown():
    assert install_mcp.resolve_agent("ayg").key == "ayg"
    assert install_mcp.resolve_agent("antigravity").key == "ayg"
    assert install_mcp.resolve_agent("cmd").key == "commandcode"
    assert install_mcp.resolve_agent("vs-code").key == "vscode"
    with pytest.raises(SystemExit):
        install_mcp.resolve_agent("not-an-agent")


def test_registry_keys_are_unique():
    keys = [agent.key for agent in install_mcp.AGENTS]
    assert len(keys) == len(set(keys))
    assert "all" not in keys


def test_upsert_json_creates_merges_and_is_idempotent(tmp_path):
    config = tmp_path / "settings.json"
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "keep"}}, "model": "x"}))

    entry = {"command": "uv", "args": ["run", "jev-mcp"]}
    assert install_mcp.upsert_json_path(config, ["mcpServers", "jev-browser"], entry) == "created"

    data = json.loads(config.read_text())
    assert data["mcpServers"]["other"] == {"command": "keep"}
    assert data["mcpServers"]["jev-browser"] == entry
    assert data["model"] == "x"

    entry["args"] = ["run", "--directory", "/tmp", "jev-mcp"]
    assert install_mcp.upsert_json_path(config, ["mcpServers", "jev-browser"], entry) == "updated"
    assert json.loads(config.read_text())["mcpServers"]["jev-browser"] == entry


def test_upsert_json_tolerates_jsonc(tmp_path):
    config = tmp_path / "mcp.json"
    config.write_text(
        '{\n  // cursor style config\n  "mcpServers": {\n'
        '    "other": {"command": "x"}, // trailing comma below and here\n  },\n}'
    )

    install_mcp.upsert_json_path(config, ["mcpServers", "jev-browser"], {"command": "uv"})
    data = json.loads(config.read_text())
    assert data["mcpServers"]["jev-browser"] == {"command": "uv"}
    assert data["mcpServers"]["other"] == {"command": "x"}


def test_upsert_toml_section_appends_then_replaces(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        'model = "gpt"\n\n[mcp_servers.other]\ncommand = "npx"\n\n[profile.test]\nname = "t"\n'
    )

    lines = ['command = "/usr/local/bin/uv"', 'args = ["run", "jev-mcp"]']
    assert install_mcp.upsert_toml_section(config, 'mcp_servers."jev-browser"', lines) == "created"
    assert install_mcp.upsert_toml_section(config, 'mcp_servers."jev-browser"', lines) == "updated"

    text = config.read_text()
    assert text.count("[mcp_servers.]") == 0
    assert text.count('mcp_servers."jev-browser"') == 1
    assert '[mcp_servers.other]\ncommand = "npx"' in text
    assert text.startswith('model = "gpt"')
    assert text.rstrip().endswith('name = "t"') or '[profile.test]' in text


def test_registration_status_lifecycle(tmp_path):
    config = tmp_path / ".cursor" / "mcp.json"
    agent = agent_with(config)

    assert install_mcp.registration_status(agent) == ("not registered", config)

    install_mcp.upsert_json_path(config, agent.json_keys, {"command": "uv"})
    assert install_mcp.registration_status(agent) == ("registered", config)

    absent = agent_with(tmp_path / ".missing" / "mcp.json", installed=False)
    assert install_mcp.registration_status(absent) == ("not installed", absent.config_path())


def test_env_key_states_never_exposes_values(tmp_path):
    env = tmp_path / ".env"
    assert install_mcp.env_key_states(env) == {"TYPESAFE_API_KEY": False, "TEXT_MODEL_API_KEY": False}

    env.write_text("TYPESAFE_API_KEY=secret-value\nTEXT_MODEL_API_KEY=\n")
    states = install_mcp.env_key_states(env)
    assert states == {"TYPESAFE_API_KEY": True, "TEXT_MODEL_API_KEY": False}
    assert "secret-value" not in json.dumps(install_mcp.env_key_states(env))
