"""Jev MCP Server - Expose browser operations for IDE agents.

This allows Cursor, VSCode Copilot, or other MCP-compatible IDEs
to control the browser using their existing licenses.

Setup:
1. Install MCP dependencies: uv sync
2. Configure in Cursor: Settings > MCP > Add Server
3. Point to this script: uv run jev-mcp

Configuration:
Pass TypeSafe credentials via MCP config (args) or environment variables:
- --typesafe-api-key or TYPESAFE_API_KEY
- --typesafe-base-url or TYPESAFE_BASE_URL (default: https://api.typesafe.ai/v1)
- --text-model-api-key or TEXT_MODEL_API_KEY
- --text-model-base-url or TEXT_MODEL_BASE_URL (default: https://api.deepseek.com/v1)
- --text-model or TEXT_MODEL (default: deepseek-chat)

Usage from IDE:
- Tool: jev_observe() → get current page state
- Tool: jev_act(action_id, text?) → execute action
- Tool: jev_navigate(url) → go to URL
- Tool: jev_close() → close browser
"""

import argparse
import json
import os
from typing import Optional

from mcp.server.mcpserver.exceptions import ToolError

from jev_ultrafast.browser import Browser

# Global browser instance (persistent across tool calls)
_browser: Optional[Browser] = None
_config: dict = {}


def setup_config(args):
    """Setup configuration from args and environment."""
    global _config

    # TypeSafe config
    _config["typesafe_api_key"] = args.typesafe_api_key or os.environ.get("TYPESAFE_API_KEY")
    _config["typesafe_base_url"] = args.typesafe_base_url or os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1")

    # Text model config
    _config["text_model_api_key"] = args.text_model_api_key or os.environ.get("TEXT_MODEL_API_KEY")
    _config["text_model_base_url"] = args.text_model_base_url or os.environ.get("TEXT_MODEL_BASE_URL", "https://api.deepseek.com/v1")
    _config["text_model"] = args.text_model or os.environ.get("TEXT_MODEL", "deepseek-chat")

    # Set environment variables for backward compatibility
    if _config["typesafe_api_key"]:
        os.environ["TYPESAFE_API_KEY"] = _config["typesafe_api_key"]
    if _config["text_model_api_key"]:
        os.environ["TEXT_MODEL_API_KEY"] = _config["text_model_api_key"]
    if _config["text_model_base_url"]:
        os.environ["TEXT_MODEL_BASE_URL"] = _config["text_model_base_url"]
    if _config["text_model"]:
        os.environ["TEXT_MODEL"] = _config["text_model"]


def get_browser():
    """Get or create browser instance."""
    global _browser
    if _browser is None:
        raise ToolError("Browser not initialized. Call jev_navigate first.")
    return _browser


def main():
    """Run MCP server with configuration."""
    from mcp.server.mcpserver import MCPServer

    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Jev MCP Server for IDE integration")
    parser.add_argument("--typesafe-api-key", help="TypeSafe API key")
    parser.add_argument("--typesafe-base-url", help="TypeSafe API base URL")
    parser.add_argument("--text-model-api-key", help="Text model API key")
    parser.add_argument("--text-model-base-url", help="Text model API base URL")
    parser.add_argument("--text-model", help="Text model name")

    args = parser.parse_args()
    setup_config(args)

    # Create MCP server
    server = MCPServer("jev-browser")

    # Register tools using decorators
    @server.tool()
    async def jev_navigate(url: str) -> str:
        """Open a URL in the browser. Creates a new browser session if none exists.

        Args:
            url: URL to navigate to
        """
        global _browser

        # Close existing browser if any
        if _browser is not None:
            try:
                _browser.close()
            except Exception:
                pass

        _browser = Browser(url)
        page = _browser.observe(screenshot=False)

        result = {
            "status": "success",
            "url": page["url"],
            "title": page["title"],
            "message": f"Navigated to {url}",
        }

        return json.dumps(result, indent=2)

    @server.tool()
    async def jev_observe(screenshot: bool = False) -> str:
        """Read current page state: URL, title, text, and interactive elements with IDs.

        Args:
            screenshot: Include screenshot (base64 JPEG). Default: false
        """
        browser = get_browser()
        page = browser.observe(screenshot=screenshot)

        # Format element table for IDE
        elements = []
        for action in page["actions"]:
            elements.append({
                "id": action["id"],
                "kind": action["kind"],
                "label": action["label"],
                "value": action.get("value", ""),
                "role": action.get("role", ""),
            })

        result = {
            "url": page["url"],
            "title": page["title"],
            "text_preview": page["text"][:2000],
            "elements": elements,
            "element_count": len(elements),
        }

        if screenshot and page.get("screenshot"):
            result["screenshot"] = f"data:image/jpeg;base64,{page['screenshot']}"

        return json.dumps(result, indent=2)

    @server.tool()
    async def jev_act(action_id: str, text: str | None = None) -> str:
        """Execute an action on an element. Use action_id from jev_observe.

        Args:
            action_id: Element ID from jev_observe (e.g., 'e1', 'e2')
            text: Text to type (required for fill actions)
        """
        browser = get_browser()

        # Get current page state
        page = browser.observe(screenshot=False)

        # Find action
        action = next((a for a in page["actions"] if a["id"] == action_id), None)
        if action is None:
            return json.dumps({"error": f"Action {action_id} not found"})

        # Execute
        try:
            browser.act(action, page, text=text)

            # Observe new state
            new_page = browser.observe(screenshot=False)

            result = {
                "status": "success",
                "executed": {
                    "action_id": action_id,
                    "kind": action["kind"],
                    "label": action["label"],
                    "text": text,
                },
                "new_url": new_page["url"],
                "new_element_count": len(new_page["actions"]),
                "message": f"Executed {action['kind']} on {action['label']}",
            }

            return json.dumps(result, indent=2)

        except Exception as e:
            return json.dumps({"error": f"Error executing action: {str(e)}"})

    @server.tool()
    async def jev_close() -> str:
        """Close the browser session."""
        global _browser

        if _browser is not None:
            try:
                _browser.close()
                _browser = None
                return json.dumps({"status": "success", "message": "Browser closed"})
            except Exception as e:
                return json.dumps({"error": f"Error closing browser: {str(e)}"})
        else:
            return json.dumps({"status": "success", "message": "No browser session to close"})

    @server.tool()
    async def jev_config(
        typesafe_api_key: str | None = None,
        typesafe_base_url: str | None = None,
        text_model_api_key: str | None = None,
        text_model_base_url: str | None = None,
        text_model: str | None = None,
    ) -> str:
        """Set or update API configuration at runtime.

        Args:
            typesafe_api_key: TypeSafe API key for operation/target selection
            typesafe_base_url: TypeSafe API base URL (default: https://api.typesafe.ai/v1)
            text_model_api_key: Text model API key for TYPE_TEXT operations
            text_model_base_url: Text model API base URL (default: https://api.deepseek.com/v1)
            text_model: Text model name (default: deepseek-chat)
        """
        global _config

        updated = []

        # Update config values
        if typesafe_api_key:
            _config["typesafe_api_key"] = typesafe_api_key
            os.environ["TYPESAFE_API_KEY"] = typesafe_api_key
            updated.append("typesafe_api_key")

        if typesafe_base_url:
            _config["typesafe_base_url"] = typesafe_base_url
            os.environ["TYPESAFE_BASE_URL"] = typesafe_base_url
            updated.append("typesafe_base_url")

        if text_model_api_key:
            _config["text_model_api_key"] = text_model_api_key
            os.environ["TEXT_MODEL_API_KEY"] = text_model_api_key
            updated.append("text_model_api_key")

        if text_model_base_url:
            _config["text_model_base_url"] = text_model_base_url
            os.environ["TEXT_MODEL_BASE_URL"] = text_model_base_url
            updated.append("text_model_base_url")

        if text_model:
            _config["text_model"] = text_model
            os.environ["TEXT_MODEL"] = text_model
            updated.append("text_model")

        # Reset text provider to use new config
        if any(key in updated for key in ["text_model_api_key", "text_model_base_url", "text_model"]):
            import jev_ultrafast.agent.model as model_module
            model_module._default_provider = None

        result = {
            "status": "success",
            "updated": updated,
            "message": f"Updated {len(updated)} config value(s)",
        }

        return json.dumps(result, indent=2)

    # Run server
    import asyncio

    async def run():
        await server.run_stdio_async()

    asyncio.run(run())


if __name__ == "__main__":
    main()
