import uuid
import asyncio
from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule
from rich.live import Live
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from langchain_mistralai import MistralAIEmbeddings
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore

from chatbot import uncompiled_builder

console = Console()
embedding_model = MistralAIEmbeddings()

COMMANDS = {
    "/exit": "Quit the chatbot",
    "/clear": "Start a new conversation (new thread)",
    "/memory": "Show what the bot remembers about you",
    "/help": "Show available commands",
}


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
    """
    On login, write the username into the store if not already present.
    This ensures identity facts are available from the very first message.
    """
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
    """Stream the assistant reply token-by-token and return the full text."""
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


async def run():
    session = PromptSession(history=InMemoryHistory())
    console.print(Rule("[bold cyan]Chatbot[/]"))

    async with AsyncSqliteSaver.from_conn_string("data/checkpoints.db") as checkpointer:
        async with AsyncSqliteStore.from_conn_string(
            "data/memory.db",
            index={"embed": embedding_model, "dims": 1024},
        ) as store:
            await store.setup()

            graph = uncompiled_builder.compile(checkpointer=checkpointer, store=store)

            user_id = (await session.prompt_async("Enter username: ")).strip() or "default"

            # FIX: seed the username into long-term memory immediately on login
            # so the bot knows who it's talking to from the very first message.
            await seed_username(store, user_id)

            thread_id = str(uuid.uuid4())
            config = {"configurable": {"user_id": user_id, "thread_id": thread_id}}

            console.print(f"\n[dim]Session started for [bold]{user_id}[/]. Type /help for commands.[/]\n")

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

                console.print("[dim]Processing...[/]")
                await stream_response(graph, user_input, config)


if __name__ == "__main__":
    asyncio.run(run())