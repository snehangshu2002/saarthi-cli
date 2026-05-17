import uuid
import asyncio
import json
import os
from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule
from rich.live import Live
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from langchain_mistralai import MistralAIEmbeddings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
import random
from chatbot import uncompiled_builder

console = Console()
embedding_model = MistralAIEmbeddings()

SETTINGS_FILE = "settings.json"


STATUS_MESSAGES = [
    "Thinking...",
    "Planning...",
    "Searching memory...",
    "Reasoning...",
    "Analyzing context...",
    "Writing response...",
    "Connecting ideas...",
    "Checking memories...",
    "Processing...",
    "Building answer..."
]
COMMANDS = {
    "/exit": "Quit the chatbot",
    "/clear": "Start a new conversation (new thread)",
    "/memory": "Show what the bot remembers about you",
    "/help": "Show available commands",
    "/settings": "Show current settings",
}

# ──────────────────────────────────────────
# Settings helpers
# ──────────────────────────────────────────

def load_settings() -> dict:
    defaults = {"username": ""}
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


# ──────────────────────────────────────────
# Chat helpers
# ──────────────────────────────────────────

def show_help():
    console.print("\n[bold yellow]Available commands:[/]")
    for cmd, desc in COMMANDS.items():
        console.print(f"  [cyan]{cmd}[/]  —  {desc}")
    console.print()


async def show_memory(store, user_id):
    try:
        items = await store.alist(("user", user_id, "details"))
    except AttributeError:
        items = await store.asearch(("user", user_id, "details"), query="user profile", limit=100)
    items = list(items)
    if not items:
        console.print("[dim]No memories stored yet.[/]\n")
        return
    console.print("\n[bold yellow]What I remember about you:[/]")
    for it in items:
        console.print(f"  [green]•[/] {it.value['data']}")
    console.print()


async def seed_username(store, user_id: str):
    """Write the username into long-term memory once on login."""
    namespace = ("user", user_id, "details")
    try:
        existing = await store.alist(namespace)
    except AttributeError:
        existing = await store.asearch(namespace, query="username name", limit=100)
    existing = list(existing)

    already_stored = any(
        user_id.lower() in it.value.get("data", "").lower()
        for it in existing
    )
    if not already_stored:
        await store.aput(namespace, str(uuid.uuid4()), {"data": f"User's username is {user_id}"})


async def stream_response(graph, user_input: str, config: dict) -> str:
    """Stream the assistant reply token-by-token."""
    full_text = ""
    console.print("\n[bold green]Bot:[/]")
    with Live("", console=console, refresh_per_second=15) as live:
        async for event in graph.astream_events(
            {"messages": [{"role": "user", "content": user_input}]},
            config=config,
            version="v2",
        ):
            kind = event.get("event")
            tags = event.get("metadata", {}).get("langgraph_node", "")
            if kind == "on_chat_model_stream" and tags == "chat":
                chunk = event["data"]["chunk"]
                token = chunk.content
                if isinstance(token, str):
                    full_text += token
                    live.update(full_text)
    console.print()
    return full_text


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

async def run():
    session = PromptSession(history=InMemoryHistory())
    console.print(Rule("[bold cyan]Chatbot[/]"))

    # Load settings and resolve username
    settings = load_settings()
    user_id = settings.get("username", "").strip()

    if not user_id:
        # First run or cleared — ask once, then persist
        user_id = (await session.prompt_async("Enter username: ")).strip() or "default"
        settings["username"] = user_id
        save_settings(settings)
        console.print(f"[dim]Username saved to {SETTINGS_FILE}. You won't be asked again.[/]")
    else:
        console.print(f"[dim]Welcome back, [bold]{user_id}[/]![/]")

    async with AsyncSqliteSaver.from_conn_string("data/checkpoints.db") as checkpointer:
        async with AsyncSqliteStore.from_conn_string(
            "data/memory.db",
            index={"embed": embedding_model, "dims": 1024},
        ) as store:
            await store.setup()

            graph = uncompiled_builder.compile(checkpointer=checkpointer, store=store)

            await seed_username(store, user_id)

            thread_id = str(uuid.uuid4())
            config = {"configurable": {"user_id": user_id, "thread_id": thread_id}}

            console.print(f"\n[dim]Session started. Type /help for commands.[/]\n")

            while True:
                try:
                    user_input = (await session.prompt_async("You: ")).strip()
                except (KeyboardInterrupt, EOFError):
                    console.print("\n[dim]Interrupted. Bye![/]")
                    break

                if not user_input:
                    continue

                if user_input == "/exit":
                    console.print("[dim]Bye![/]")
                    break

                elif user_input == "/help":
                    show_help()
                    continue

                elif user_input == "/settings":
                    console.print(f"\n[bold yellow]Current settings:[/]")
                    for k, v in load_settings().items():
                        console.print(f"  [cyan]{k}[/]: {v}")
                    console.print()
                    continue

                elif user_input == "/clear":
                    thread_id = str(uuid.uuid4())
                    config["configurable"]["thread_id"] = thread_id
                    console.print("[dim]New conversation started.[/]\n")
                    continue

                elif user_input == "/memory":
                    await show_memory(store, user_id)
                    continue

                elif user_input.startswith("/"):
                    console.print(f"[red]Unknown command:[/] {user_input}. Type /help.\n")
                    continue

                with console.status(
                    f"[dim]{random.choice(STATUS_MESSAGES)}[/]",
                    spinner="dots"
                ):
                    await stream_response(graph, user_input, config)


if __name__ == "__main__":
    asyncio.run(run())