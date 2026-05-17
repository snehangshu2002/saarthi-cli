import asyncio
import os
import random
import uuid

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.store.sqlite.aio import AsyncSqliteStore
from rich.console import Console
from rich.rule import Rule

from chatbot_cli.app_config import COMMANDS, DATA_DIR, STATUS_MESSAGES
from chatbot_cli.chatbot import build_graph
from chatbot_cli.formatting import format_checkpoint_time, render_messages
from chatbot_cli.memory import seed_username
from chatbot_cli.providers import get_models
from chatbot_cli.sessions import list_user_sessions, load_thread_snapshot
from chatbot_cli.settings import first_run_setup, load_settings, settings_complete
from chatbot_cli.streaming import stream_response
from chatbot_cli.ui import ChatUI, create_chat_session

console = Console()


def start_new_conversation(user_id: str) -> dict:
    new_thread_id = str(uuid.uuid4())
    return {"configurable": {"user_id": user_id, "thread_id": new_thread_id}}


async def run():
    os.makedirs(DATA_DIR, exist_ok=True)
    session = create_chat_session()

    console.print(Rule("[bold cyan]Chatbot[/]"))

    settings = load_settings()
    if not settings_complete(settings):
        settings = await first_run_setup(session)
    else:
        console.print(f"[dim]Welcome back, [bold]{settings['username']}[/]![/]")

    user_id = settings["username"]
    provider = settings["provider"]
    api_key = settings["api_key"]

    try:
        model, embedding_model, dims = get_models(provider, api_key)
    except Exception as e:
        console.print(f"[red]Failed to load provider '{provider}': {e}[/]")
        console.print("[dim]Edit settings.json and restart.[/]")
        return

    async with AsyncSqliteSaver.from_conn_string(f"{DATA_DIR}/checkpoints.db") as checkpointer:
        async with AsyncSqliteStore.from_conn_string(
            f"{DATA_DIR}/memory.db",
            index={"embed": embedding_model, "dims": dims},
        ) as store:
            await store.setup()

            graph = build_graph(model, checkpointer, store)
            await seed_username(store, user_id)

            ui = ChatUI()
            config = start_new_conversation(user_id)
            ui.append_block("Welcome back, " + settings["username"] + "!")
            ui.append_block("New session started. Type /help for commands.")

            async def chat_loop():
                nonlocal config
                resume_options = None

                while True:
                    try:
                        user_input = (await ui.prompt()).strip()
                    except (KeyboardInterrupt, EOFError):
                        ui.append_block("Bye!")
                        ui.app.exit()
                        break

                    if not user_input:
                        continue

                    if resume_options is not None:
                        if user_input == "__cancel_select__":
                            ui.append_block("Resume cancelled.")
                            resume_options = None
                            ui.cancel_selection()
                            continue

                        if user_input != "__select__":
                            continue

                        selected = ui.current_selection()
                        if selected is None:
                            resume_options = None
                            ui.cancel_selection()
                            continue

                        resume_options = None
                        ui.cancel_selection()
                        config = {
                            "configurable": {
                                "user_id": user_id,
                                "thread_id": selected["thread_id"],
                            }
                        }

                        snapshot = await load_thread_snapshot(checkpointer, selected["thread_id"])
                        ui.clear_transcript()
                        if snapshot is not None:
                            messages = snapshot.checkpoint.get("channel_values", {}).get("messages", [])
                            transcript = render_messages(messages)
                            if transcript:
                                ui.append_block(transcript)
                        ui.append_block(
                            "Resumed session: "
                            + format_checkpoint_time(selected["ts"])
                            + f"  ({selected['thread_id'][:8]})"
                        )
                        continue

                    ui.append_block(f"> {user_input}")

                    if user_input == "/exit":
                        ui.append_block("Bye!")
                        ui.app.exit()
                        break

                    if user_input == "/help":
                        lines = ["Available commands:"]
                        for cmd, desc in COMMANDS.items():
                            lines.append(f"  {cmd}  -  {desc}")
                        ui.append_block("\n".join(lines))
                        continue

                    if user_input == "/settings":
                        saved_settings = load_settings()
                        lines = ["Current settings:"]
                        for key, value in saved_settings.items():
                            display = value[:6] + "..." if key == "api_key" and len(value) > 6 else value
                            lines.append(f"  {key}: {display}")
                        ui.append_block("\n".join(lines))
                        continue

                    if user_input == "/new":
                        config = start_new_conversation(user_id)
                        ui.clear_transcript()
                        ui.append_block("New conversation started. Type /help for commands.")
                        continue

                    if user_input == "/resume":
                        sessions = await list_user_sessions(checkpointer, user_id)
                        if not sessions:
                            ui.append_block("No saved conversations found.")
                            continue

                        resume_options = sessions
                        ui.start_selection(
                            "Saved conversations:",
                            sessions,
                            "Use Up/Down and Enter to resume. Esc or Ctrl+C cancels.",
                        )
                        continue

                    if user_input.startswith("/"):
                        ui.append_block(f"Unknown command: {user_input}. Type /help.")
                        continue

                    ui.set_status(random.choice(STATUS_MESSAGES))
                    try:
                        await stream_response(graph, user_input, config, ui)
                    finally:
                        ui.set_status("")

            await ui.run(chat_loop)


def main():
    asyncio.run(run())
