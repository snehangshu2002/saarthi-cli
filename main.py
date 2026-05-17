import uuid
import asyncio
import json
import os
import random

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule
from rich.live import Live
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.shortcuts import radiolist_dialog, input_dialog, message_dialog
from langchain_core.messages import AIMessageChunk
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore

from chatbot import build_graph
from providers import get_models, SUPPORTED_PROVIDERS

console = Console()

SETTINGS_FILE = "settings.json"
DATA_DIR      = "data"

STATUS_MESSAGES = [
    "Thinking...", "Planning...","Reasoning...", "Analyzing context...", 
    "Writing response...","Connecting ideas...", "Processing...","Building answer...",
]

COMMANDS = {
    "/exit":     "Quit the chatbot",
    "/new":      "Start a new conversation",
    # "/memory":   "Show what the bot remembers about you",
    "/help":     "Show available commands",
    "/settings": "Show current settings",
}

# ──────────────────────────────────────────
# Settings helpers
# ──────────────────────────────────────────

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


# ──────────────────────────────────────────
# First-run setup
# ──────────────────────────────────────────

async def first_run_setup(session: PromptSession) -> dict:
    """
    Interactive first-run wizard — fully dialog driven.
    Step 1: username  (plain prompt)
    Step 2: provider  (radiolist dialog — ↑↓ + Enter)
    Step 3: api key   (input_dialog with password=True — hidden, Enter confirms)
    Step 4: summary   (message_dialog — shows selected model, masked key)
    """
    console.print(Rule("[bold cyan]First time setup[/]"))
    console.print("[dim]This runs once. Answers are saved to settings.json.[/]\n")

    # ── step 1: username ──
    username = (await session.prompt_async("Choose a username: ")).strip()
    if not username:
        username = "default"

    # ── step 2: provider via radiolist dialog ──
    # radiolist: space selects, Enter confirms — works without clicking OK
    provider = await radiolist_dialog(
        title="Step 1 of 2 — Select AI Provider",
        text="Use  ↑ ↓  to move,  Space  to select,  Enter  to confirm.",
        values=[(key, label) for key, label in SUPPORTED_PROVIDERS.items()],
        default="mistral",
        ok_text="Continue →",
        cancel_text="Quit",
    ).run_async()

    if provider is None:
        console.print("[yellow]Setup cancelled.[/]")
        raise SystemExit(0)

    # ── step 3: api key via input_dialog (password=True hides input) ──
    key_hints = {
        "mistral": "console.mistral.ai",
        "openai":  "platform.openai.com",
        "google":  "aistudio.google.com",
    }
    provider_label = SUPPORTED_PROVIDERS[provider]

    api_key = await input_dialog(
        title="Step 2 of 2 — API Key",
        text=(
            f"Provider: {provider_label}\n\n"
            f"Paste your API key below.\n"
            f"Get it at: {key_hints.get(provider, '')}\n\n"
            f"(Input is hidden)"
        ),
        password=True,
        ok_text="Save →",
        cancel_text="Back",
    ).run_async()

    if api_key is None:
        # user hit Back — restart setup
        console.print("[dim]Going back...[/]")
        return await first_run_setup(session)

    api_key = api_key.strip()
    if not api_key:
        console.print("[red]No API key entered. Edit settings.json to add it later.[/]")

    # ── step 4: confirmation dialog ──
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
        ok_text="Start Chatting →",
    ).run_async()

    settings = {
        "username": username,
        "provider": provider,
        "api_key":  api_key,
    }
    save_settings(settings)
    return settings


# ──────────────────────────────────────────
# Memory helpers
# ──────────────────────────────────────────

# async def show_memory(store, user_id: str):
#     items = await store.asearch(("user", user_id, "details"), query=None, limit=500)
#     if not items:
#         console.print("[dim]No memories stored yet.[/]\n")
#         return
#     console.print("\n[bold yellow]What I remember about you:[/]")
#     for it in items:
#         console.print(f"  [green]•[/] {it.value['data']}")
#     console.print()


async def seed_username(store, user_id: str):
    namespace = ("user", user_id, "details")
    existing  = await store.asearch(namespace, query=None, limit=500)
    already   = any(user_id.lower() in it.value.get("data", "").lower() for it in existing)
    if not already:
        await store.aput(namespace, str(uuid.uuid4()), {"data": f"User's username is {user_id}"})


# ──────────────────────────────────────────
# Streaming response
# ──────────────────────────────────────────

async def stream_response(graph, user_input: str, config: dict) -> str:
    full_text = ""
    console.print("\n[bold green]Bot:[/]")

    with Live("", console=console, refresh_per_second=15) as live:
        async for chunk, metadata in graph.astream(
            {"messages": [{"role": "user", "content": user_input}]},
            config=config,
            stream_mode="messages",
        ):
            if (
                metadata.get("langgraph_node") == "chat"
                and isinstance(chunk, AIMessageChunk)
                and isinstance(chunk.content, str)
                and chunk.content
            ):
                full_text += chunk.content
                live.update(full_text)

    console.print()

    if not full_text:
        console.print("[red]No response received. Check your API key in settings.json.[/]")

    return full_text


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

async def run():
    os.makedirs(DATA_DIR, exist_ok=True)
    session = PromptSession(history=InMemoryHistory())

    console.print(Rule("[bold cyan]Chatbot[/]"))

    # ── resolve settings ──
    settings = load_settings()

    if not settings_complete(settings):
        settings = await first_run_setup(session)
    else:
        console.print(f"[dim]Welcome back, [bold]{settings['username']}[/]![/]")

    user_id  = settings["username"]
    provider = settings["provider"]
    api_key  = settings["api_key"]

    # ── init models ──
    try:
        model, embedding_model, dims = get_models(provider, api_key)
    except Exception as e:
        console.print(f"[red]Failed to load provider '{provider}': {e}[/]")
        console.print("[dim]Edit settings.json and restart.[/]")
        return

    # ── open db connections ──
    async with AsyncSqliteSaver.from_conn_string(f"{DATA_DIR}/checkpoints.db") as checkpointer:
        async with AsyncSqliteStore.from_conn_string(
            f"{DATA_DIR}/memory.db",
            index={"embed": embedding_model, "dims": dims},
        ) as store:
            await store.setup()

            graph = build_graph(model, checkpointer, store)
            await seed_username(store, user_id)

            def start_new_conversation() -> dict:
                new_thread_id = str(uuid.uuid4())
                return {"configurable": {"user_id": user_id, "thread_id": new_thread_id}}

            # always start fresh on launch
            config = start_new_conversation()
            console.print(f"\n[dim]New session started. Type /help for commands.[/]\n")

            # ── chat loop ──
            while True:
                try:
                    user_input = (await session.prompt_async("You: ")).strip()
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[dim]Bye![/]")
                    break

                if not user_input:
                    continue

                if user_input == "/exit":
                    console.print("[dim]Bye![/]")
                    break

                elif user_input == "/help":
                    console.print("\n[bold yellow]Available commands:[/]")
                    for cmd, desc in COMMANDS.items():
                        console.print(f"  [cyan]{cmd}[/]  —  {desc}")
                    console.print()

                elif user_input == "/settings":
                    console.print("\n[bold yellow]Current settings:[/]")
                    s = load_settings()
                    for k, v in s.items():
                        # mask api key
                        display = v[:6] + "..." if k == "api_key" and len(v) > 6 else v
                        console.print(f"  [cyan]{k}[/]: {display}")
                    console.print()

                elif user_input == "/new":
                    config = start_new_conversation()
                    session = PromptSession(history=InMemoryHistory())
                    console.clear()
                    console.print(Rule("[bold cyan]Chatbot[/]"))
                    console.print("[dim]New conversation started.[/]\n")

                # elif user_input == "/memory":
                #     await show_memory(store, user_id)

                elif user_input.startswith("/"):
                    console.print(f"[red]Unknown command:[/] {user_input}. Type /help.\n")

                else:
                    console.print(f"[dim]{random.choice(STATUS_MESSAGES)}[/]", end="\r")
                    await stream_response(graph, user_input, config)


if __name__ == "__main__":
    asyncio.run(run())
