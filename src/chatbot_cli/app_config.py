import os
from pathlib import Path

from prompt_toolkit.styles import Style

# Platform-appropriate user data directory
def get_user_data_dir() -> Path:
    """Get the platform-specific user data directory."""
    if os.name == "nt":  # Windows
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    elif os.name == "posix":
        if "XDG_DATA_HOME" in os.environ:
            base = Path(os.environ["XDG_DATA_HOME"])
        else:
            base = Path.home() / ".local" / "share"
    else:
        base = Path.home() / ".saarthi"
    return base / "saarthi"

USER_DATA_DIR = get_user_data_dir()
SETTINGS_FILE = str(USER_DATA_DIR / "settings.json")
DATA_DIR = str(USER_DATA_DIR / "data")

STATUS_MESSAGES = [
    "Thinking...",
    "Planning...",
    "Reasoning...",
    "Analyzing context...",
    "Writing response...",
    "Connecting ideas...",
    "Processing...",
    "Building answer...",
]

COMMANDS = {
    "/exit": "Quit the chatbot",
    "/new": "Start a new conversation",
    "/resume": "Resume an older conversation",
    "/mcp": "List connected MCP servers and their tools",
    "/export": "Export current chat history to a text file",
    "/plan": "Toggle Plan Mode (AI plans steps before tool execution)",
    "/help": "Show available commands",
    "/settings": "Show current settings (run '/settings edit' to update)",
}

APP_STYLE = Style.from_dict(
    {
        "transcript": "",
        "status": "#ff8c00",
        "input": "",
        "user-line": "bg:#2a2a2a #ffffff",
        # Tool block rendering
        "tool-header": "#5fd7ff bold",        # bright cyan header line
        "tool-hint": "#555555 italic",         # dim grey "Ctrl+T to see full" hint
        "tool-separator": "#333333",           # dim separator lines
        # Completion menu
        "completion-menu": "bg:default",
        "completion-menu.completion": "bg:default",
        "completion-menu.completion.current": "reverse",
        "completion-menu.meta.completion": "bg:default",
        "completion-menu.meta.completion.current": "reverse",
    }
)