"""Jev Desktop MCP server — expose macOS Accessibility app control for IDE agents.

The coding agent is the brain; this server only observes and executes. It calls
no model and needs no API keys.

Tools:
- desktop_attach(app)      attach to one allowlisted app by bundle id
- desktop_observe()        indexed element table (menu bar, tabs, fields, buttons)
- desktop_act(action_id, text?)   trusted AXPress / AXValue write, guard-checked
- desktop_close()          detach

Security: only apps in JEV_DESKTOP_ALLOW (comma-separated bundle ids,
default "com.google.Chrome") can be attached. An Accessibility-trusted process
can drive any app on the machine — keep the allowlist tight.
"""

import json
import os
from typing import Optional

from jev_ultrafast.desktop import DesktopApp, StaleState
from jev_ultrafast.desktop.ax import ElementGone

DEFAULT_ALLOW = "com.google.Chrome"

_desktop: Optional[DesktopApp] = None


def allowed_apps() -> list[str]:
    raw = os.environ.get("JEV_DESKTOP_ALLOW", DEFAULT_ALLOW)
    return [item.strip() for item in raw.split(",") if item.strip()]


def error(message: str) -> str:
    return json.dumps({"error": message}, indent=2)


def attach_app(app: str) -> str:
    global _desktop
    if app not in allowed_apps():
        return error(
            f"'{app}' is not in the desktop allowlist. Set JEV_DESKTOP_ALLOW "
            f"(comma-separated bundle ids, default '{DEFAULT_ALLOW}') to extend it."
        )
    if _desktop is not None:
        _desktop.close()
    _desktop = DesktopApp(app)
    try:
        page = _desktop.observe()
    except StaleState as exc:
        _desktop = None
        return error(str(exc))
    return json.dumps({
        "status": "success",
        "app": app,
        "title": page["title"],
        "windows": page["windows"],
        "element_count": len([a for a in page["actions"] if a["kind"] != "wait"]),
        "message": f"Attached to {app}. Use desktop_observe for the element table.",
    }, indent=2)


def get_desktop() -> DesktopApp:
    if _desktop is None:
        raise StaleState("No desktop session. Call desktop_attach first.")
    return _desktop


def observe_state() -> str:
    try:
        page = get_desktop().observe()
    except (StaleState, ElementGone) as exc:
        return error(f"{exc}")
    elements = [
        {"id": a["id"], "kind": a["kind"], "label": a["label"], "value": a.get("value", ""), "role": a.get("role", "")}
        for a in page["actions"]
    ]
    return json.dumps({
        "app": page["app"],
        "title": page["title"],
        "windows": page["windows"],
        "text_preview": page["text"][:2000],
        "elements": elements,
        "element_count": len(elements),
    }, indent=2)


def act_by_id(action_id: str, text: str | None = None) -> str:
    try:
        app = get_desktop()
        page = app.observe()
        action = next((a for a in page["actions"] if a["id"] == action_id), None)
        if action is None:
            return error(f"Action {action_id} not found. Observe again; ids change with each snapshot.")
        app.act(action, page, text=text)
        new_page = app.observe()
        return json.dumps({
            "status": "success",
            "executed": {"action_id": action_id, "kind": action["kind"], "label": action["label"], "text": text},
            "new_title": new_page["title"],
            "new_element_count": len([a for a in new_page["actions"] if a["kind"] != "wait"]),
            "message": f"Executed {action['kind']} on {action['label']}",
        }, indent=2)
    except StaleState as exc:
        return error(f"{exc}")
    except ElementGone:
        close_app()
        return error("The app quit or restarted. Call desktop_attach again.")


def close_app() -> str:
    global _desktop
    if _desktop is None:
        return json.dumps({"status": "success", "message": "No desktop session"}, indent=2)
    _desktop.close()
    _desktop = None
    return json.dumps({"status": "success", "message": "Desktop session closed"}, indent=2)


def main():
    from mcp.server.mcpserver import MCPServer

    server = MCPServer("jev-desktop")

    @server.tool()
    async def desktop_attach(app: str) -> str:
        """Attach to one allowlisted desktop app by bundle id (e.g. com.google.Chrome).

        Args:
            app: Bundle id from JEV_DESKTOP_ALLOW (default allowlist: com.google.Chrome)
        """
        return attach_app(app)

    @server.tool()
    async def desktop_observe() -> str:
        """Read the app state: title, text preview, and interactive elements with IDs."""
        return observe_state()

    @server.tool()
    async def desktop_act(action_id: str, text: str | None = None) -> str:
        """Execute an action on an element. Use action_id from desktop_observe.

        Args:
            action_id: Element ID from desktop_observe (e.g. 'e1')
            text: Text to type (required for fill actions)
        """
        return act_by_id(action_id, text)

    @server.tool()
    async def desktop_close() -> str:
        """Detach from the app."""
        return close_app()

    import asyncio

    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()
