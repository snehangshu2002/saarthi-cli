import json
import os

from prompt_toolkit.shortcuts import input_dialog, message_dialog, radiolist_dialog
from rich.console import Console
from rich.rule import Rule
from pathlib import Path
from chatbot_cli.app_config import SETTINGS_FILE, USER_DATA_DIR
from chatbot_cli.providers import SUPPORTED_PROVIDERS

console = Console()

MCP_CONFIG_PATH = USER_DATA_DIR / "mcp_config.json"
DEFAULT_MCP_CONFIG = {
    "mcpServers": {
        "filesystem": {
            "command": "npx",
            "args": [
                "-y",
                "@modelcontextprotocol/server-filesystem",
                str(Path.home())   # resolves to C:\Users\SNEHANGSHU on your machine
                                   # resolves to /home/username on Linux/Mac
            ],
            "transport": "stdio"
        }
    }
}


def ensure_mcp_config():
    """Create mcp_config.json with defaults if it doesn't exist."""
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        if not MCP_CONFIG_PATH.exists():
            MCP_CONFIG_PATH.write_text(
                json.dumps(DEFAULT_MCP_CONFIG, indent=2),
                encoding="utf-8",
            )
            return True   # created fresh
        return False      # already existed
    except OSError as e:
        console.print(f"[yellow]Warning: could not write mcp_config.json — {e}[/]")
        return False


def load_settings() -> dict:
    """Read settings.json from disk."""
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    defaults = {"username": "", "provider": "", "api_key": ""}
    if not os.path.exists(SETTINGS_FILE):
        save_settings(defaults)
        return defaults
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {**defaults, **data}
    except (json.JSONDecodeError, OSError):
        save_settings(defaults)
        return defaults


def save_settings(settings: dict) -> None:
    """Write settings dict to JSON file."""
    try:
        USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError as e:
        console.print(f"[red]Error: could not save settings — {e}[/]")


def settings_complete(settings: dict) -> bool:
    """True only if all required fields are filled."""
    return bool(
        settings.get("username", "").strip()
        and settings.get("provider", "").strip()
        and settings.get("api_key", "").strip()
    )


async def first_run_setup(session, _depth: int = 0) -> dict:
    """
    Interactive first-run wizard. Loops on Back, but caps recursion at 10
    to avoid a stack overflow on repeated cancels.
    """
    if _depth > 10:
        console.print("[red]Too many retries during setup. Exiting.[/]")
        raise SystemExit(1)

    console.print(Rule("[bold cyan]First time setup[/]"))
    console.print("[dim]This runs once. Answers are saved to settings.json.[/]\n")

    try:
        username = (await session.prompt_async("Choose a username: ")).strip()
    except (EOFError, KeyboardInterrupt):
        console.print("[yellow]Setup cancelled.[/]")
        raise SystemExit(0)

    if not username:
        username = "default"

    provider = await radiolist_dialog(
        title="Step 1 of 2 - Select AI Provider",
        text="Use Up/Down to move, Space to select, Enter to confirm.",
        values=[(key, label) for key, label in SUPPORTED_PROVIDERS.items()],
        default="mistral",
        ok_text="Continue",
        cancel_text="Quit",
    ).run_async()

    if provider is None:
        console.print("[yellow]Setup cancelled.[/]")
        raise SystemExit(0)

    key_hints = {
        "mistral": "console.mistral.ai",
        "openai": "platform.openai.com",
        "google": "aistudio.google.com",
    }
    provider_label = SUPPORTED_PROVIDERS[provider]

    api_key = await input_dialog(
        title="Step 2 of 2 - API Key",
        text=(
            f"Provider: {provider_label}\n\n"
            f"Paste your API key below.\n"
            f"Get it at: {key_hints.get(provider, '')}\n\n"
            f"(Input is hidden)"
        ),
        password=True,
        ok_text="Save",
        cancel_text="Back",
    ).run_async()

    if api_key is None:
        console.print("[dim]Going back...[/]")
        return await first_run_setup(session, _depth=_depth + 1)

    api_key = api_key.strip()
    if not api_key:
        console.print("[red]No API key entered. Edit settings.json to add it later.[/]")

    masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "****"
    await message_dialog(
        title="Setup Complete",
        text=(
            f"  Username : {username}\n"
            f"  Provider : {provider_label}\n"
            f"  API key  : {masked_key}\n\n"
            f"Settings saved to {SETTINGS_FILE}.\n"
            f"Press Enter to start chatting."
        ),
        ok_text="Start Chatting",
    ).run_async()

    settings = {
        "username": username,
        "provider": provider,
        "api_key": api_key,
    }
    save_settings(settings)
    return settings