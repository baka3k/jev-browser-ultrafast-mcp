# Text Provider Guide

## Overview

Jev Ultrafast uses **TypeSafe (Jev)** for operation/target selection (không thể thay thế), but the **text generation** for TYPE_TEXT operations can use any LLM provider.

```
┌─────────────────────────────────────────────┐
│  TypeSafe (Jev) - FIXED                     │
│  - Chọn operation (CLICK/TYPE/SELECT)       │
│  - Chọn target từ element table             │
│  - Speculative fan-out, 1 request           │
│  - KHÔNG THỂ THAY THẾ                       │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────┐
│  Text Provider - CÓ THỂ THAY THẾ            │
│  - Chỉ sinh text cho TYPE_TEXT operations   │
│  - Hiện tại: Mercury-2.5 qua OpenRouter     │
│  - Có thể thay: Claude, GPT-4, etc.         │
└─────────────────────────────────────────────┘
```

## Current configuration

Mặc định sử dụng OpenAI-compatible provider:

```bash
# .env
TEXT_MODEL_BASE_URL=https://openrouter.ai/api/v1
TEXT_MODEL=inception/mercury-2.5
TEXT_MODEL_API_KEY=your_openrouter_key
```

## Using a different provider

### Option 1: Environment variables (OpenAI-compatible)

Bất kỳ API nào tương thích OpenAI format:

```bash
# OpenRouter
TEXT_MODEL_BASE_URL=https://openrouter.ai/api/v1
TEXT_MODEL=anthropic/claude-3.5-sonnet
TEXT_MODEL_API_KEY=sk-or-...

# DeepSeek
TEXT_MODEL_BASE_URL=https://api.deepseek.com/v1
TEXT_MODEL=deepseek-chat
TEXT_MODEL_API_KEY=sk-...

# OpenAI
TEXT_MODEL_BASE_URL=https://api.openai.com/v1
TEXT_MODEL=gpt-4-turbo
TEXT_MODEL_API_KEY=sk-...

# Local Ollama
TEXT_MODEL_BASE_URL=http://localhost:11434/v1
TEXT_MODEL=llama3.1
TEXT_MODEL_API_KEY=unused
```

### Option 2: Custom provider (programmatic)

Implement `TextProvider` interface:

```python
from jev_ultrafast.agent.model import set_text_provider

class ClaudeTextProvider:
    """Custom Claude provider with different error handling."""
    
    def generate(self, context: dict) -> tuple[str, dict]:
        """
        Args:
            context: {
                "goal": "Find flights from Zurich to London",
                "field": {"label": "Where from?", "role": "combobox", "value": ""},
                "page": {"title": "Google Flights", "text": "..."},
                "recent_actions": [{"action": "Click", "text": None}]
            }
        
        Returns:
            (text_value, metadata)
        """
        import anthropic
        import time
        
        client = anthropic.Anthropic()
        
        prompt = f"""Generate text for field: {context['field']['label']}
Goal: {context['goal']}
Page context: {context['page']['text'][:1000]}

Return JSON: {{"text": "the value to type"}}"""

        started = time.perf_counter()
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}]
        )
        
        import json
        output = json.loads(response.content[0].text)
        
        return output["text"], {
            "model": "claude-3-5-sonnet",
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "usage": {"input_tokens": response.usage.input_tokens, "output_tokens": response.usage.output_tokens}
        }

# Set custom provider
set_text_provider(ClaudeTextProvider())
```

### Option 3: Codex/OpenCode provider

```python
class CodexTextProvider:
    """Use Codex CLI as text provider."""
    
    def generate(self, context: dict) -> tuple[str, dict]:
        import subprocess
        import time
        
        prompt = f"Generate value for {context['field']['label']}: {context['goal']}"
        
        started = time.perf_counter()
        result = subprocess.run(
            ["codex", "-q", prompt],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        # Parse JSON from output
        import json
        output = json.loads(result.stdout)
        
        return output["text"], {
            "model": "codex-cli",
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "usage": {}
        }

set_text_provider(CodexTextProvider())
```

## Example: Switching providers at runtime

```python
from jev_ultrafast import Agent
from jev_ultrafast.agent.model import set_text_provider, OpenAICompatibleProvider

# Use GPT-4 for text generation
gpt4_provider = OpenAICompatibleProvider(
    base_url="https://api.openai.com/v1",
    api_key="sk-...",
    model="gpt-4-turbo"
)
set_text_provider(gpt4_provider)

# Run agent (TypeSafe still chooses operations/targets)
agent = Agent(
    "https://www.google.com/travel/flights",
    "Find flights from Zurich to London"
)

for state in agent.run():
    print(state["status"])
```

## Performance comparison

| Provider | Latency | Cost/1K chars | Quality |
|----------|---------|---------------|---------|
| Mercury-2.5 (default) | ~200ms | ~$0.001 | Good for simple fields |
| Claude 3.5 Sonnet | ~500ms | ~$0.003 | Better for complex reasoning |
| GPT-4 Turbo | ~800ms | ~$0.01 | Best quality, slowest |
| DeepSeek V3 | ~300ms | ~$0.0005 | Cheap, decent quality |

**Recommendation:** Start with Mercury-2.5 (default). Only upgrade if you see quality issues in text generation.

## What TypeSafe does (cannot be replaced)

TypeSafe là phần **core intelligence** của Jev:

1. **Nhận element table** từ browser
2. **Quyết định operation**: CLICK, TYPE_TEXT, SELECT, WAIT, DONE, BLOCKED
3. **Chọn target** từ danh sách elements (speculative fan-out)
4. **Trả về trong 1 request** (~200ms)

Ví dụ output:
```json
{
  "operation": "TYPE_TEXT",
  "target": "2",
  "choice": "e2",
  "confidence": 0.95,
  "probabilities": {"e1": 0.03, "e2": 0.95, "e3": 0.02}
}
```

Sau khi TypeSafe chọn TYPE_TEXT, **text provider** sẽ được gọi để sinh giá trị text.

## Architecture diagram

```
User goal
    ↓
┌─────────────────────────────────┐
│  Browser.observe()              │
│  → element table                │
└────────────┬────────────────────┘
             │
             ↓
┌─────────────────────────────────┐
│  TypeSafe (Jev)                 │  ← FIXED, không thể thay thế
│  - Input: element table + goal  │
│  - Output: operation + target   │
│  - Latency: ~200ms              │
└────────────┬────────────────────┘
             │
             ├─→ CLICK, SELECT, WAIT, DONE, BLOCKED
             │   (execute directly)
             │
             └─→ TYPE_TEXT
                 │
                 ↓
        ┌─────────────────┐
        │  Text Provider  │  ← CÓ THỂ THAY THẾ
        │  - Input: field │
        │    context      │
        │  - Output: text │
        │    value        │
        └────────┬────────┘
                 │
                 ↓
        ┌─────────────────┐
        │  Browser.act()  │
        │  - Execute      │
        │    action       │
        └─────────────────┘
```

## Summary

- **TypeSafe (Jev)**: Không thể thay thế, là core intelligence
- **Text Provider**: Có thể thay thế qua env vars hoặc custom implementation
- **Browser Layer**: Đã tách riêng, có thể dùng độc lập
- **Agent Loop**: Giữ nguyên, chỉ thay đổi text provider nếu cần
