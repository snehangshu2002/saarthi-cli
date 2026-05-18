# Saarthi CLI

> *Saarthi* (सारथी) means guide or companion in Hindi.

**Your AI copilot in the terminal.**

Saarthi is a LangGraph-powered CLI chatbot with persistent memory, real-time token streaming, MCP integration, and multi-provider LLM support. It runs entirely inside the terminal with a custom TUI built using `prompt-toolkit`.

No browser. No Electron. No cloud dashboard.

[![PyPI version](https://img.shields.io/pypi/v/saarthi-cli)](https://pypi.org/project/saarthi-cli/)
[![Python Versions](https://img.shields.io/pypi/pyversions/saarthi-cli)](https://pypi.org/project/saarthi-cli/)
[![License](https://img.shields.io/github/license/snehangshu2002/saarthi-cli)](https://github.com/snehangshu2002/saarthi-cli/blob/main/LICENSE)
[![GitHub release](https://img.shields.io/github/v/release/snehangshu2002/saarthi-cli)](https://github.com/snehangshu2002/saarthi-cli/releases)

---

## Demo

![Saarthi CLI demo](https://raw.githubusercontent.com/snehangshu2002/saarthi-cli/main/img/temp.png)

---

## Features

- Short-term and long-term memory support
- Local SQLite-backed conversation persistence
- Named chat sessions with resume support
- Real-time token streaming
- Live tool-call visualisation
- MCP (Model Context Protocol) server support
- Interactive terminal UI built with `prompt-toolkit`
- Multi-provider LLM support
- Local-first architecture — no data leaves your machine
- Built-in developer tools

---

## Supported providers

- OpenAI
- Google Gemini
- Mistral AI

More providers (including Anthropic and local model support) are planned.

---

## Built-in tools

| Tool           | Description                                |
| -------------- | ------------------------------------------ |
| `bash`         | Execute shell commands and Python snippets |
| `calculator`   | Evaluate mathematical expressions          |
| `ddg_tool`     | DuckDuckGo web search                      |
| `wiki_tool`    | Wikipedia lookup                           |
| `arxiv_tool`   | arXiv paper search                         |

---

## Installation

### Using pip

```bash
pip install saarthi-cli
saarthi
```

### Using uv

```bash
uv tool install saarthi-cli
saarthi
```

### From source

```bash
git clone https://github.com/snehangshu2002/saarthi-cli.git
cd saarthi-cli
uv sync
uv run python main.py
```

### Linux / macOS install script

```bash
curl -fsSL https://raw.githubusercontent.com/snehangshu2002/saarthi-cli/main/install.sh | bash
```

---

## First-time setup

On first launch, Saarthi walks you through a one-time setup:

1. Choose a username
2. Select an LLM provider
3. Enter your API key (input is hidden)

---

## Local storage

All configuration and memory are stored locally — nothing is sent to any external service beyond your chosen LLM provider.

| Platform      | Storage Path                  |
| ------------- | ----------------------------- |
| Windows       | `%LOCALAPPDATA%\saarthi\`     |
| Linux / macOS | `~/.local/share/saarthi/`     |

Contents:

- `settings.json` — provider and user config
- `mcp_config.json` — MCP server definitions
- SQLite database — conversation memory

---

## Commands

| Command      | Description                  |
| ------------ | ---------------------------- |
| `/help`      | Show available commands       |
| `/new`       | Start a new session           |
| `/resume`    | Resume an older session       |
| `/settings`  | View current configuration    |
| `/mcp`       | Show connected MCP servers    |
| `/exit`      | Quit Saarthi                  |

---

## MCP support

Saarthi supports MCP-compatible servers over STDIO transport. Edit `mcp_config.json` in your local storage directory to add servers.

Default configuration:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/path/to/dir"
      ],
      "transport": "stdio"
    }
  }
}
```

You can connect MCP servers for filesystem access, browser automation, databases, coding agents, external APIs, and custom tools.

---

## Memory system

Saarthi supports two memory layers:

- **Short-term memory** — active conversation context
- **Long-term memory** — persisted locally in SQLite across sessions

Conversation history can also be summarised automatically to reduce context size while preserving important information.

---

## Roadmap

- [ ] Human-in-the-loop workflows
- [ ] Planning mode
- [ ] Autonomous execution mode
- [ ] Skill system support
- [ ] Export conversations
- [ ] Anthropic and local model support
- [ ] Plugin-style custom tools
- [ ] Better configuration management
- [ ] More CLI-agent style workflows

---

## Project structure

```text
src/chatbot_cli/
├── app.py
├── chatbot.py
├── ui.py
├── streaming.py
├── tool.py
├── memory.py
├── sessions.py
├── providers.py
├── mcp_client.py
├── settings.py
└── clipboard.py
```

---

## License

MIT — see [LICENSE](./LICENSE) for details.
