from prompt_toolkit.styles import Style


SETTINGS_FILE = "settings.json"
DATA_DIR = "data"

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
    "/help": "Show available commands",
    "/settings": "Show current settings",
}

APP_STYLE = Style.from_dict(
    {
        "transcript": "",
        "status": "#ff8c00",
        "input": "",
        "user-line": "bg:#2a2a2a #ffffff",
        "completion-menu": "bg:default",
        "completion-menu.completion": "bg:default",
        "completion-menu.completion.current": "reverse",
        "completion-menu.meta.completion": "bg:default",
        "completion-menu.meta.completion.current": "reverse",
    }
)