# Release Notes: Saarthi CLI vX.X.X

## 🚀 New Features & Enhancements

### 1. Markdown Skill Support (`.md` Prompts)
- **New Feature:** The Skill System now natively supports Markdown (`.md`) files as reusable prompts, alongside Python scripts! 
- You can now save raw LLM instructions (e.g., `translate to pirate speak`) into a `.md` file in your `skills/` directory using the new `save_md_skill` internal tool.
- When executed, the CLI dynamically injects these instructions directly into the LLM context without running any Python subprocesses.

### 2. Interactive Terminal Hyperlinks (Clickable Files)
- **New Feature:** Any absolute file path outputted by the AI (e.g., `C:\Users\...` or `/home/...`) is now **auto-detected, underlined, and made clickable**.
- **How it works:** Simply click the file path in the terminal, and the CLI will seamlessly open it in your operating system's default editor (using `os.startfile` on Windows or `webbrowser.open` on Mac/Linux).

### 3. Unified `/skills` UI Picker & Aliases
- Removed the deprecated manual `/skill show` and `/skill delete` console output clutter.
- The `/skills` command now triggers a beautiful interactive TUI picker, allowing you to browse, read descriptions, and execute skills visually.
- **Improved Parsing:** The CLI now correctly handles both `/skill` and `/skills` prefixes interchangeably and gracefully strips accidental `.md` or `.py` extensions typed by the user.

### 4. Cleaner Sub-Agent Tool Outputs
- **UI Polish:** Drastically improved the formatting of sub-agent tool snippets (such as reading massive webpages via `fetch_webpage`). 
- Newlines and excess vertical whitespace in tool outputs are now automatically collapsed, keeping your terminal UI clean, compact, and free of massive blocks of text.

### 5. `?` Shortcuts Menu
- **UI Polish:** Implemented a new `?` status-bar shortcut menu. If your input buffer is empty, pressing `?` reveals a quick reference for handy keyboard shortcuts like Plan Mode toggles and Copy Mode directly in the status bar.

### 6. MCP Configuration Fixes
- **Bug Fix:** Fixed an issue where dynamically added MCP servers were failing to parse. The documentation and internal config generation now strictly enforce the `"transport": "stdio"` key required for the standard MCP adapter.

## 📝 Documentation
- Completely updated the `README.md` to reflect the new Markdown Skills, the clickable paths, and the unified UI picker logic.
- Dynamically injected the OS-specific `skills/` and `mcp_config.json` paths into the internal AI System Prompt, meaning the AI always knows exactly where your local configuration files live without guessing!
