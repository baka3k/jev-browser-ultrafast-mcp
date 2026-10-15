"""Example: Using different text providers with TypeSafe.

TypeSafe (Jev) vẫn quyết định operation/target.
Text provider chỉ sinh text cho TYPE_TEXT operations.

Usage:
    uv run --env-file .env python examples/custom_text_provider.py
"""

import os
import time

from jev_ultrafast import Agent
from jev_ultrafast.agent.model import OpenAICompatibleProvider, set_text_provider


class SlowButCheapProvider:
    """Example: DeepSeek with custom settings."""

    def __init__(self):
        self.provider = OpenAICompatibleProvider(
            base_url="https://api.deepseek.com/v1",
            api_key=os.environ.get("TEXT_MODEL_API_KEY"),
            model="deepseek-chat",
            reasoning={"thinking": {"type": "disabled"}},
        )

    def generate(self, context: dict) -> tuple[str, dict]:
        # Add custom logging or processing
        print(f"[SlowButCheapProvider] Generating text for: {context['field']['label']}")

        text, metadata = self.provider.generate(context)

        print(f"[SlowButCheapProvider] Generated: {text} (latency: {metadata['latency_ms']}ms)")
        return text, metadata


class FastLocalProvider:
    """Example: Local Ollama for zero cost."""

    def generate(self, context: dict) -> tuple[str, dict]:
        import httpx

        # Use local Ollama
        client = httpx.Client(timeout=10)

        prompt = f"""Generate a value for the field "{context['field']['label']}".
Goal: {context['goal']}

Return JSON: {{"text": "the value"}}"""

        started = time.perf_counter()

        try:
            response = client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "llama3.1",
                    "prompt": prompt,
                    "stream": False,
                },
            )

            if response.status_code != 200:
                raise RuntimeError(f"Ollama error: {response.status_code}")

            import json

            output = json.loads(response.json()["response"])
            text = output["text"]

        except Exception:
            # Fallback to simple heuristic
            field_label = context["field"]["label"].lower()
            if "from" in field_label or "origin" in field_label:
                text = "Zurich"
            elif "to" in field_label or "destination" in field_label:
                text = "London"
            else:
                text = "test"

        return text, {
            "model": "local-ollama",
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "usage": {},
        }


def main():
    # Choose provider
    provider_choice = os.environ.get("TEXT_PROVIDER", "default")

    if provider_choice == "slow-cheap":
        print("Using SlowButCheapProvider (DeepSeek)")
        set_text_provider(SlowButCheapProvider())
    elif provider_choice == "local":
        print("Using FastLocalProvider (Ollama)")
        set_text_provider(FastLocalProvider())
    else:
        print("Using default provider (Mercury-2.5 via OpenRouter)")
        # Default provider is already set from env vars

    # Run agent
    url = "https://www.google.com/travel/flights?hl=en"
    goal = "Find one-way flights from Zurich to London on September 20, 2026"

    print(f"\nStarting agent with goal: {goal}\n")

    agent = Agent(url, goal)

    try:
        for state in agent.run():
            last = state["history"][-1] if state["history"] else {}
            text_info = f" (text: {last.get('text')})" if last.get("text") else ""
            print(
                f"{state['elapsed_ms']:>5} ms | {state['status']:10s} | "
                f"{last.get('operation', ''):10s} | {last.get('action', '')}{text_info}"
            )

            # Show text provider metadata
            if last.get("text_helper"):
                print(f"      └─ Text provider: {last['text_helper']}")

    finally:
        agent.close()

    print("\n✓ Done")


if __name__ == "__main__":
    main()
