# Saarthi CLI

**Your AI copilot in the terminal.** Saarthi is a sophisticated command-line chatbot powered by LangGraph with long-term memory, multiple AI provider support, and an interactive TUI built with prompt-toolkit.

> **Note**: This is version 0.1.0 — the first release. More features, improvements, and providers coming soon!

[![PyPI version](https://badge.fury.io/py/saarthi-cli.svg)](https://pypi.org/project/saarthi-cli/)
[![Python](https://img.shields.io/pypi/pyversions/saarthi-cli.svg)](https://pypi.org/project/saarthi-cli/)
[![GitHub](https://img.shields.io/github/v/release/snehangshu2002/saarthi-cli?label=github)](https://github.com/snehangshu2002/saarthi-cli)

## Features

- **Multi-Provider Support**: Works with Mistral AI, OpenAI, and Google Gemini
- **LangGraph Memory**: Persistent long-term memory using SQLite-backed stores
- **Session Management**: Save and resume conversations across sessions
- **Streaming Output**: Real-time streaming responses with tool execution visualization
- **MCP Integration**: Connect external tools via Model Context Protocol servers
- **Built-in Tools**: Bash execution, calculator, web search (DuckDuckGo), Wikipedia, arXiv

## Requirements

- Python 3.12+
- API key for one of the supported providers (Mistral, OpenAI, or Google)

## Quickstart

```bash
# Install (from PyPI when published)
pip install saarthi-cli

# Run
saarthi
```

## First-Time Setup

On first run, you'll be prompted to:
1. Choose a username
2. Select an AI provider (Mistral, OpenAI, or Google)
3. Enter your API key

Settings and data are stored in your user data directory:
- **Windows**: `%LOCALAPPDATA%\saarthi\`
- **Linux/Mac**: `~/.local/share/saarthi/`

## Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all available commands |
| `/new` | Start a fresh conversation |
| `/resume` | Restore a previous conversation |
| `/exit` | Quit the chatbot |
| `/settings` | Display current configuration |
| `/mcp` | List connected MCP servers and tools |

### Text Selection & Copying

- **Mouse**: Hold `Shift`, click and drag to highlight, right-click or `Ctrl+C` to copy
- **Keyboard**: `Ctrl+Space` to start selection, arrow keys to expand, `Ctrl+C` to copy

## Project Structure

```
.
├── src/chatbot_cli/        Application package
│   ├── __init__.py         Package init
│   ├── app.py              Main entry point and chat loop
│   ├── app_config.py       Configuration constants and styles
│   ├── chatbot.py          LangGraph graph definition with memory nodes
│   ├── streaming.py        Response streaming logic
│   ├── ui.py               prompt-toolkit TUI components
│   ├── tool.py             Built-in tools (bash, calculator, search)
│   ├── mcp_client.py       MCP server integration
│   ├── providers.py        Multi-provider model initialization
│   ├── settings.py         User settings management
│   ├── memory.py           Memory utilities
│   └── sessions.py         Session listing and loading
├── notebooks/              Experiments and scratch notebooks
├── main.py                 Local development launcher
├── pyproject.toml          Package configuration
└── README.md               This file
```

**Data directory**: `%LOCALAPPDATA%\saarthi\` (Windows) or `~/.local/share/saarthi/` (Linux/Mac) contains `settings.json`, `mcp_config.json`, and SQLite databases.

## Development

```bash
# Clone and install in editable mode
git clone https://github.com/snehangshu2002/saarthi-cli.git
cd saarthi-cli
uv sync

# Run from source
uv run python main.py
```

**Note**: When running from source, settings and data are stored in your user data directory (`%LOCALAPPDATA%\saarthi\` on Windows, `~/.local/share/saarthi/` on Linux/Mac), not in the project directory.

## Building & Publishing

```bash
# Build the package
uv build

# Upload to PyPI (requires account)
uv publish

# Or using twine
uv build
twine upload dist/*
```

## Changelog

### 0.1.0 (2026-05-18)
- Initial release
- LangGraph-powered CLI with long-term memory
- Multi-provider support (Mistral, OpenAI, Google)
- Session management and resume functionality
- MCP server integration
- Built-in tools: bash, calculator, web search, Wikipedia, arXiv

## MCP Servers

The chatbot can connect to external MCP servers. A default `mcp_config.json` is created in your data directory on first run with the filesystem server enabled. Edit this file to add more servers.

**Location**: 
- Windows: `%LOCALAPPDATA%\saarthi\mcp_config.json`
- Linux/Mac: `~/.local/share/saarthi/mcp_config.json`

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]
    }
  }
}
```

## Built-in Tools

| Tool | Description |
|------|-------------|
| `bash` | Execute shell commands or Python code (30s timeout) |
| `calculator` | Evaluate mathematical expressions |
| `ddg_tool` | DuckDuckGo web search |
| `wiki_tool` | Wikipedia article lookup |
| `arxiv_tool` | arXiv paper search |

## Architecture

The chatbot uses a LangGraph state machine with the following nodes:

1. **chat** - Calls the LLM with conversation history and user memories
2. **tools** - Executes tool calls from the LLM response
3. **tool_followup** - Processes tool results and generates follow-up response
4. **summarize** - Compresses conversation history to maintain context window
5. **remember** - Extracts and persists user facts to long-term memory

## Roadmap

- [ ] Additional AI providers (Anthropic, Cohere, local models)
- [ ] Custom tool plugins
- [ ] Conversation export/import
- [ ] Shell command auto-detection and suggestions
- [ ] Multi-line conversation history navigation
- [ ] Theme customization

## License

MIT