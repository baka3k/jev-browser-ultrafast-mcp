# Jev Ultrafast — build, install, doctor.
#   make build              prepare the full environment (deps, .env, JS checks, lint, tests, package)
#   make install [agent]    register the jev-browser MCP server with coding agents (default: all)
#   make install-all        also register jev-desktop (macOS AX; explicit opt-in)
#   make doctor             health check for the whole browser stack

AGENT ?= all

# Accept a positional agent: make install cursor
ifneq ($(filter install install-dry install-all,$(MAKECMDGOALS)),)
  ifneq ($(word 2,$(MAKECMDGOALS)),)
    AGENT := $(word 2,$(MAKECMDGOALS))
  endif
endif

KNOWN_AGENTS := all claude codex commandcode cmd cmdcode vscode code vs-code vs cursor qwen ayg agy agv anti antigravity gemini opencode zcode

.DEFAULT_GOAL := help
.PHONY: help sync build js-check lint test install install-all install-dry check-desktop doctor clean

help:
	@echo "Jev Ultrafast"
	@echo "  make build                prepare environment: deps, .env scaffold, JS checks, lint, tests, package"
	@echo "  make install [agent]      register jev-browser for: claude codex commandcode vscode cursor"
	@echo "                            qwen ayg (Antigravity) gemini opencode zcode — or all (default)"
	@echo "  make install-all [agent]  also register jev-desktop (macOS AX) — explicit opt-in"
	@echo "  make install-dry [agent]  show what install would write, change nothing"
	@echo "  make check-desktop        live AX check against real Chrome (skips when unavailable)"
	@echo "  make doctor               health check: deps, API keys, Chrome, browser-harness, AX, MCP"
	@echo "  make sync | js-check | lint | test | clean"

sync:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	@uv sync
	@if [ ! -f .env ]; then cp .env.example .env; echo "Created .env from .env.example — add TYPESAFE_API_KEY and TEXT_MODEL_API_KEY."; fi

build: sync js-check lint test
	@uv build
	@echo "Build complete: dependencies installed, checks passed, package in dist/."

js-check:
	@command -v node >/dev/null 2>&1 || { echo "node is required for JS syntax checks. Install Node.js first."; exit 1; }
	@node --check jev_ultrafast/static/app.js
	@node --check jev_ultrafast/browser/snapshot.js
	@echo "JS files OK."

lint:
	@uv run ruff check .

test:
	@uv run pytest -q

install: sync
	@uv run python scripts/install_mcp.py --agent "$(AGENT)" --project "$(CURDIR)"

install-all: sync
	@uv run python scripts/install_mcp.py --agent "$(AGENT)" --server all --project "$(CURDIR)"

install-dry:
	@uv run python scripts/install_mcp.py --agent "$(AGENT)" --project "$(CURDIR)" --dry-run

check-desktop:
	@uv run python scripts/check_ax.py

doctor:
	@command -v uv >/dev/null 2>&1 || { echo "uv is not installed. Install: curl -LsSf https://astral.sh/uv/install.sh | sh"; exit 1; }
	@uv run python scripts/doctor.py --project "$(CURDIR)"

clean:
	@rm -rf dist .pytest_cache .ruff_cache
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +

# Positional agent names (make install cursor) need a rule so make accepts the extra goal.
%:
	@case " $(KNOWN_AGENTS) " in \
	  *" $@ "*) \
	    if [ -z "$(filter install install-dry,$(MAKECMDGOALS))" ]; then \
	      echo "Nothing to do for '$@' — did you mean 'make install $@'?"; \
	    fi ;; \
	  *) echo "make: *** unknown target '$@'. Run 'make help'."; exit 1 ;; \
	esac
