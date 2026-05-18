# Saarthi CLI

**Your AI copilot in the terminal.**

Saarthi is a command-line chatbot built on LangGraph with long-term memory, multi-provider support, real-time streaming, and an interactive TUI powered by prompt-toolkit. It runs fully inside your terminal — no browser, no Electron, no cloud dashboard.

> Version 0.1.0 — first public release. More providers and features are on the way.

[![PyPI version](https://badge.fury.io/py/saarthi-cli.svg)](https://pypi.org/project/saarthi-cli/)
[![Python](https://img.shields.io/pypi/pyversions/saarthi-cli.svg)](https://pypi.org/project/saarthi-cli/)
[![GitHub](https://img.shields.io/github/v/release/snehangshu2002/saarthi-cli?label=github)](https://github.com/snehangshu2002/saarthi-cli)

---

## What it does

- Keeps a **long-term memory** of things you tell it, stored in a local SQLite database
- Streams responses token by token with a live spinner and tool-call visualisation
- Connects to external services via **MCP (Model Context Protocol)** servers
- Ships five **built-in tools**: bash/Python execution, calculator, DuckDuckGo search, Wikipedia, and arXiv
- Saves and restores **named sessions** so you can pick up any conversation later
- Works with **Mistral AI**, **OpenAI**, and **Google Gemini** — you choose at setup

---

## Requirements

- Python 3.12 or newer
- An API key for at least one supported provider

---

## Installation

```bash
pip install saarthi-cli
```

Then run it:

```bash
saarthi
```

### Install from source

```bash
git clone https://github.com/snehangshu2002/saarthi-cli.git
cd saarthi-cli
uv sync
uv run python main.py
```

---

## First-time setup

On first run, Saarthi walks you through a three-step wizard:

1. Pick a username
2. Choose a provider (Mistral, OpenAI, or Google)
3. Paste your API key (input is hidden)

Settings are written to `settings.json` in your data directory and reused on every subsequent launch. You can edit this file directly or re-run setup with `/settings`.

**Where data is stored:**

| Platform | Path |
|----------|------|
| Windows | `%LOCALAPPDATA%\saarthi\` |
| Linux / Mac | `~/.local/share/saarthi/` |

This directory holds `settings.json`, `mcp_config.json`, and the SQLite memory database.

---

## Commands

| Command | What it does |
|---------|--------------|
| `/help` | List all commands |
| `/new` | Start a fresh conversation |
| `/resume` | Pick up a saved conversation |
| `/settings` | Show current configuration |
| `/mcp` | List connected MCP servers and their tools |
| `/exit` | Quit |

### Copying text

| Method | Steps |
|--------|-------|
| Mouse | Hold `Shift`, click and drag to highlight, then right-click or `Ctrl+C` |
| Keyboard | `Ctrl+Space` to start selection, arrow keys to extend, `Ctrl+C` to copy |

---

## Built-in tools

| Tool | Description |
|------|-------------|
| `bash` | Run shell commands or Python snippets (30 s timeout) |
| `calculator` | Evaluate maths expressions |
| `ddg_tool` | DuckDuckGo web search |
| `wiki_tool` | Wikipedia article lookup |
| `arxiv_tool` | arXiv paper search |

---

## MCP servers

Saarthi can connect to any MCP-compatible server. A default `mcp_config.json` is created on first run with the filesystem server enabled.

**Config location:**

| Platform | Path |
|----------|------|
| Windows | `%LOCALAPPDATA%\saarthi\mcp_config.json` |
| Linux / Mac | `~/.local/share/saarthi/mcp_config.json` |

Edit this file to add more servers:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"],
      "transport": "stdio"
    },
    "my-custom-server": {
      "command": "python",
      "args": ["-m", "my_mcp_server"],
      "transport": "stdio"
    }
  }
}
```

Any server that speaks the MCP STDIO transport works here.

---

## Architecture

Saarthi uses a LangGraph state machine. Each user message passes through these nodes in order:

```
user input
    │
    ▼
 chat           ← calls the LLM with conversation history + user memories
    │
    ▼ (if tools called)
 tools          ← executes tool calls in parallel
    │
    ▼
 tool_followup  ← sends tool results back to the LLM for a follow-up reply
    │
    ▼ (every N turns)
 summarize      ← compresses old history to keep the context window manageable
    │
    ▼
 remember       ← extracts facts about the user and writes them to long-term memory
```

Memory is backed by a local SQLite store (via LangGraph's built-in checkpointer). Sessions are identified by a thread ID, so you can have multiple independent conversations running.

---

## Project layout

```
.
├── src/chatbot_cli/
│   ├── app.py           Main entry point and chat loop
│   ├── app_config.py    Constants, styles, and command definitions
│   ├── chatbot.py       LangGraph graph definition
│   ├── streaming.py     Token-streaming and tool-call rendering
│   ├── ui.py            prompt-toolkit TUI (layout, key bindings, transcript)
│   ├── tool.py          Built-in tools
│   ├── mcp_client.py    MCP server connection and tool discovery
│   ├── providers.py     Lazy provider imports (Mistral / OpenAI / Google)
│   ├── settings.py      Settings load/save and first-run wizard
│   ├── memory.py        Memory extraction helpers
│   ├── sessions.py      Session listing and resume logic
│   └── clipboard.py     Windows clipboard integration
├── notebooks/           Scratch notebooks
├── main.py              Local dev launcher
├── pyproject.toml       Package config
└── README.md
```

---

## Development

```bash
# Clone and install in editable mode
git clone https://github.com/snehangshu2002/saarthi-cli.git
cd saarthi-cli
uv sync

# Run
uv run python main.py
```

---

## Building and publishing

```bash
# Build
uv build

# Publish to PyPI
uv publish

# Or with twine
uv build
twine upload dist/*
```

---

## Changelog

### 0.1.0 (2026-05-18)

- Initial release
- LangGraph-powered CLI with long-term memory (SQLite)
- Multi-provider support: Mistral AI, OpenAI, Google Gemini
- Real-time streaming with tool-call visualisation
- Session save and resume
- MCP server integration (STDIO transport)
- Built-in tools: bash, calculator, DuckDuckGo, Wikipedia, arXiv
- First-run setup wizard with masked API key input

---

## Roadmap

- Anthropic Claude, Cohere, and local model support
- Custom tool plugins
- Conversation export and import
- Shell command auto-detection
- Multi-line history navigation
- Theme customisation

---

## License

MIT