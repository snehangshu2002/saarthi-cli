import json
import os

from prompt_toolkit.shortcuts import input_dialog, message_dialog, radiolist_dialog
from rich.console import Console
from rich.rule import Rule
from pathlib import Path
from chatbot_cli.app_config import SETTINGS_FILE, USER_DATA_DIR
from chatbot_cli.providers import SUPPORTED_PROVIDERS, DEFAULT_MODELS, PROVIDER_MODELS

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
    defaults = {
        "username": "",
        "provider": "",
        "model": "",
        "api_key": "",
        "api_keys": {},
        "embedding_provider": "",
        "embedding_model": ""
    }
    if not os.path.exists(SETTINGS_FILE):
        save_settings(defaults)
        return defaults
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Migrate old structure: copy provider api_key to api_keys map if exists
        if "provider" in data and "api_key" in data and data["provider"] and data["api_key"]:
            api_keys = data.setdefault("api_keys", {})
            if data["provider"] not in api_keys:
                api_keys[data["provider"]] = data["api_key"]
        
        # Populate model defaults if missing
        provider = data.get("provider", "")
        if provider and not data.get("model"):
            data["model"] = DEFAULT_MODELS.get(provider, "")
            
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
    provider = settings.get("provider", "").strip()
    if not settings.get("username", "").strip() or not provider:
        return False
    if provider == "ollama":
        return True
    
    # Check both the legacy global api_key or the entry in the api_keys dict
    active_key = settings.get("api_key", "").strip()
    if not active_key and "api_keys" in settings:
        active_key = settings["api_keys"].get(provider, "").strip()
    return bool(active_key)


async def first_run_setup(session, _depth: int = 0) -> dict:
    """
    Interactive setup wizard. Loops on Back, but caps recursion at 10
    to avoid a stack overflow on repeated cancels.
    """
    if _depth > 10:
        console.print("[red]Too many retries during setup. Exiting.[/]")
        raise SystemExit(1)

    console.print(Rule("[bold cyan]Setup Wizard[/]"))
    console.print("[dim]Configure your AI provider and preferences. Settings are saved to settings.json.[/]\n")

    # Load existing settings so we can pre-populate fields
    existing = load_settings()
    username_default = existing.get("username") or ""

    try:
        username = (await session.prompt_async("Choose a username: ", default=username_default)).strip()
    except (EOFError, KeyboardInterrupt):
        console.print("[yellow]Setup cancelled.[/]")
        raise SystemExit(0)

    if not username:
        username = "default"

    # Select AI provider
    provider = await radiolist_dialog(
        title="Step 1 of 3 - Select AI Provider",
        text="Use Up/Down to move, Space to select, Enter to confirm.",
        values=[(key, label) for key, label in SUPPORTED_PROVIDERS.items()],
        default=existing.get("provider") or "mistral",
        ok_text="Continue",
        cancel_text="Quit",
    ).run_async()

    if provider is None:
        console.print("[yellow]Setup cancelled.[/]")
        raise SystemExit(0)

    # API key (except Ollama)
    api_keys = existing.get("api_keys", {})
    if existing.get("api_key") and existing.get("provider") == provider:
        api_keys[provider] = existing.get("api_key")
        
    api_key = ""
    if provider != "ollama":
        key_hints = {
            "mistral": "console.mistral.ai",
            "openai": "platform.openai.com",
            "google": "aistudio.google.com",
            "anthropic": "console.anthropic.com",
        }
        provider_label = SUPPORTED_PROVIDERS[provider]
        existing_key = api_keys.get(provider, "")

        api_key = await input_dialog(
            title="Step 2 of 3 - API Key",
            text=(
                f"Provider: {provider_label}\n\n"
                f"Paste your API key below.\n"
                f"Get it at: {key_hints.get(provider, '')}\n\n"
                f"(Input is hidden)"
            ),
            default=existing_key,
            password=True,
            ok_text="Continue",
            cancel_text="Back",
        ).run_async()

        if api_key is None:
            console.print("[dim]Going back...[/]")
            return await first_run_setup(session, _depth=_depth + 1)

        api_key = api_key.strip()
        if not api_key:
            console.print("[red]No API key entered.[/]")
        
        api_keys[provider] = api_key

    # Select model
    models_list = PROVIDER_MODELS.get(provider, [])
    default_model = existing.get("model") if existing.get("provider") == provider else DEFAULT_MODELS.get(provider, "")
    if default_model not in models_list:
        default_model = DEFAULT_MODELS.get(provider, "")

    dialog_values = [(m, m) for m in models_list]
    dialog_values.append(("custom", "Custom model name..."))

    selected_model = await radiolist_dialog(
        title="Step 3 of 3 - Select Chat Model",
        text=f"Choose a chat model for {SUPPORTED_PROVIDERS[provider]}.\nUse Up/Down to move, Space to select, Enter to confirm.",
        values=dialog_values,
        default=default_model or (models_list[0] if models_list else "custom"),
        ok_text="Continue",
        cancel_text="Back",
    ).run_async()

    if selected_model is None:
        console.print("[dim]Going back...[/]")
        return await first_run_setup(session, _depth=_depth + 1)

    if selected_model == "custom":
        custom_model = await input_dialog(
            title="Custom Model Name",
            text="Type the exact model identifier (e.g., gpt-4o-mini or claude-3-5-haiku-latest):",
            default=existing.get("model") if existing.get("provider") == provider else "",
            ok_text="Save",
            cancel_text="Back",
        ).run_async()
        if custom_model is None:
            return await first_run_setup(session, _depth=_depth + 1)
        selected_model = custom_model.strip()
        if not selected_model:
            selected_model = DEFAULT_MODELS.get(provider, "")

    # Set default embedding based on chat provider
    if provider == "google":
        embedding_provider = "google"
        embedding_model = "models/embedding-001"
    elif provider == "openai":
        embedding_provider = "openai"
        embedding_model = "text-embedding-3-small"
    elif provider == "mistral":
        embedding_provider = "mistral"
        embedding_model = "mistral-embed"
    elif provider == "ollama":
        embedding_provider = "ollama"
        embedding_model = "nomic-embed-text"
    else:  # anthropic / other fallback
        embedding_provider = "local"
        embedding_model = ""

    # Confirmation
    masked_key = "****"
    if provider != "ollama" and api_key:
        masked_key = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "****"

    provider_label = SUPPORTED_PROVIDERS[provider]
    await message_dialog(
        title="Setup Complete",
        text=(
            f"  Username : {username}\n"
            f"  Provider : {provider_label}\n"
            f"  Model    : {selected_model}\n"
            f"  API key  : {masked_key if provider != 'ollama' else 'Not required'}\n"
            f"  Embedder : {embedding_provider} ({embedding_model or 'local fake'})\n\n"
            f"Settings saved to {SETTINGS_FILE}.\n"
            f"Press Enter to start chatting."
        ),
        ok_text="Start Chatting",
    ).run_async()

    settings = {
        "username": username,
        "provider": provider,
        "model": selected_model,
        "api_key": api_key,  # Keep legacy key populated for backward compatibility
        "api_keys": api_keys,
        "embedding_provider": embedding_provider,
        "embedding_model": embedding_model,
    }
    save_settings(settings)
    return settings