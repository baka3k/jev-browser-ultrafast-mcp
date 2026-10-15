"""Example: external agent driving the browser layer.

This shows how Claude Code, Codex, or any external agent can drive
the browser as a lightweight controller.

Replace `external_agent_decide()` with your actual agent implementation.
"""

from jev_ultrafast.browser import Browser, StalePage


def external_agent_decide(page_state, goal, history):
    """
    External agent decides what to do next.

    Args:
        page_state: dict from browser.observe()
        goal: user's goal string
        history: list of previous actions taken

    Returns:
        (action_id, text) for fill actions
        (action_id, None) for click/select
        ("DONE", None) when goal is satisfied
        ("BLOCKED", None) when no progress possible

    Example implementation:
        # Serialize page_state to prompt
        elements = "\\n".join(
            f"  [{a['id']}] {a['kind']}: {a['label']} = {a.get('value', '')}"
            for a in page_state['actions']
        )
        prompt = f"Goal: {goal}\\nURL: {page_state['url']}\\nElements:\\n{elements}"

        # Call Claude/Codex/your agent
        response = call_your_agent(prompt)

        # Parse response
        return parse_action(response)
    """
    raise NotImplementedError("Replace with your external agent implementation")


def main():
    url = "https://www.google.com"
    goal = "Search for Python documentation"

    browser = Browser(url)
    history = []

    try:
        while True:
            # 1. Observe current state
            page = browser.observe()

            # 2. Ask external agent what to do
            action_id, text = external_agent_decide(page, goal, history)

            # 3. Check for termination
            if action_id == "DONE":
                print("Goal satisfied!")
                break
            if action_id == "BLOCKED":
                print("Cannot make progress")
                break

            # 4. Find the action
            action = next((a for a in page["actions"] if a["id"] == action_id), None)
            if not action:
                print(f"Action {action_id} not found in current page")
                break

            # 5. Execute with staleness handling
            try:
                browser.act(action, page, text=text)
                history.append(
                    {
                        "action": action["label"],
                        "kind": action["kind"],
                        "text": text,
                    }
                )
            except StalePage:
                print("Page changed, re-observing...")
                continue

    finally:
        browser.close()


if __name__ == "__main__":
    main()
