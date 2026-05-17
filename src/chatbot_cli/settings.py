import json
import os

from prompt_toolkit.shortcuts import input_dialog, message_dialog, radiolist_dialog
from rich.console import Console
from rich.rule import Rule

from chatbot_cli.app_config import SETTINGS_FILE
from chatbot_cli.providers import SUPPORTED_PROVIDERS

console = Console()


def load_settings() -> dict:
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
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


def settings_complete(settings: dict) -> bool:
    """True only if all required fields are filled."""
    return bool(
        settings.get("username", "").strip()
        and settings.get("provider", "").strip()
        and settings.get("api_key", "").strip()
    )


async def first_run_setup(session) -> dict:
    console.print(Rule("[bold cyan]First time setup[/]"))
    console.print("[dim]This runs once. Answers are saved to settings.json.[/]\n")

    username = (await session.prompt_async("Choose a username: ")).strip()
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
        return await first_run_setup(session)

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
