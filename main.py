import uuid
from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule
from prompt_toolkit import prompt
from prompt_toolkit.history import InMemoryHistory

from chatbot import graph,store

console = Console()
history = InMemoryHistory()

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
    items = await store.search(("user", user_id, "details"))
    if not items:
        console.print("[dim]No memories stored yet.[/]\n")
        return
    console.print("\n[bold yellow]What I remember about you:[/]")
    for it in items:
        console.print(f"  [green]•[/] {it.value['data']}")
    console.print()

async def run():
    # ask for username once at start
    console.print(Rule("[bold cyan]Chatbot[/]"))
    user_id = prompt("Enter username: ").strip() or "default"
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"user_id": user_id, "thread_id": thread_id}}

    console.print(f"\n[dim]Session started for [bold]{user_id}[/]. Type /help for commands.[/]\n")

    while True:
        try:
            user_input = prompt("You: ", history=history).strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]Interrupted. Bye![/]")
            break

        if not user_input:
            continue

        # --- handle slash commands ---
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
            from chatbot import store   # import the store from your graph module
            await show_memory(store, user_id)
            continue

        elif user_input.startswith("/"):
            console.print(f"[red]Unknown command:[/] {user_input}. Type /help.\n")
            continue

        # --- normal chat turn ---
        with console.status("[cyan]Thinking...[/]", spinner="dots"):
            result = await graph.ainvoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config
            )

        response = result["messages"][-1].content

        console.print(f"\n[bold green]Bot:[/]")
        console.print(Markdown(response))
        console.print()

if __name__ == "__main__":
    asyncio.run(run())