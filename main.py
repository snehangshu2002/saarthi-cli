import uuid
import asyncio
import json
import os
import random
import subprocess
from datetime import datetime

from rich.console import Console
from rich.rule import Rule
from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.clipboard import Clipboard, ClipboardData
from prompt_toolkit.document import Document
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.containers import Float, FloatContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.shortcuts import radiolist_dialog, input_dialog, message_dialog
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea
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
    "/resume":   "Resume an older conversation",
    # "/memory":   "Show what the bot remembers about you",
    "/help":     "Show available commands",
    "/settings": "Show current settings",
}

APP_STYLE = Style.from_dict(
    {
        "transcript": "",
        "status": "",
        "input": "",
        "completion-menu": "",
        "completion-menu.completion.current": "reverse",
        "completion-menu.meta.completion": "",
        "completion-menu.meta.completion.current": "reverse",
    }
)


class WindowsClipboard(Clipboard):
    def get_data(self) -> ClipboardData:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return ClipboardData("")

        if result.returncode != 0:
            return ClipboardData("")
        return ClipboardData(result.stdout.rstrip("\r\n"))

    def set_data(self, data: ClipboardData) -> None:
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "Set-Clipboard"],
                input=data.text,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return


class SlashCommandCompleter(Completer):
    """Show slash commands only while typing a command at the prompt."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if not text.startswith("/") or " " in text:
            return

        for command, description in COMMANDS.items():
            if command.startswith(text):
                yield Completion(
                    command,
                    start_position=-len(text),
                    display=command,
                    display_meta=description,
                )


def build_key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("enter")
    def _(event):
        buffer = event.app.current_buffer
        if buffer.complete_state and buffer.complete_state.current_completion:
            buffer.apply_completion(buffer.complete_state.current_completion)
        buffer.validate_and_handle()

    return bindings


def create_chat_session() -> PromptSession:
    return PromptSession(
        history=InMemoryHistory(),
        completer=SlashCommandCompleter(),
        complete_while_typing=True,
        key_bindings=build_key_bindings(),
    )


def _message_content_text(message) -> str:
    content = getattr(message, "content", "")
    if isinstance(message, dict):
        content = message.get("content", "")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return " ".join(
            part.get("text", "").strip()
            for part in content
            if isinstance(part, dict) and part.get("text")
        ).strip()
    return str(content).strip()


def _message_role(message) -> str:
    if isinstance(message, dict):
        return str(message.get("role", ""))
    msg_type = getattr(message, "type", "")
    if msg_type:
        return str(msg_type)
    return type(message).__name__.replace("Message", "").lower()


def _clip_text(text: str, limit: int = 90) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _format_checkpoint_time(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


def _checkpoint_preview(checkpoint_tuple) -> str:
    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
    summary = channel_values.get("summary")
    if isinstance(summary, str) and summary.strip():
        return _clip_text(summary)

    messages = channel_values.get("messages", [])
    for message in reversed(messages):
        text = _message_content_text(message)
        if text.startswith("Task exception was never retrieved"):
            continue
        if text:
            return _clip_text(text)

    return "No saved preview"


def _render_messages(messages: list) -> str:
    blocks = []
    for message in messages:
        role = _message_role(message)
        content = _message_content_text(message)
        if not content:
            continue
        if role in {"human", "user"}:
            blocks.append(f"You: {content}")
        elif role in {"ai", "assistant"}:
            blocks.append(f"Bot:\n{content}")
    return "\n\n".join(blocks)


async def list_user_sessions(checkpointer, user_id: str, limit: int = 20) -> list[dict]:
    sessions = []
    seen_threads = set()

    async for item in checkpointer.alist(None, filter={"user_id": user_id}, limit=200):
        thread_id = item.config["configurable"]["thread_id"]
        if thread_id in seen_threads:
            continue
        seen_threads.add(thread_id)
        sessions.append(
            {
                "thread_id": thread_id,
                "ts": item.checkpoint.get("ts", ""),
                "label": f"{_format_checkpoint_time(item.checkpoint.get('ts', ''))}  {_checkpoint_preview(item)}",
            }
        )

    return sessions[:limit]


async def load_thread_snapshot(checkpointer, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    return await checkpointer.aget_tuple(config)


class ChatUI:
    def __init__(self):
        self._history = InMemoryHistory()
        self._transcript_text = ""
        self._pending_input = None
        self._stream_anchor = None
        self._status = ""
        self._selection_options = []
        self._selection_index = 0
        self._selection_title = ""
        self._selection_instruction = ""

        self.transcript = TextArea(
            text="",
            read_only=True,
            focusable=True,
            focus_on_click=True,
            scrollbar=True,
            wrap_lines=True,
            style="class:transcript",
        )
        self.input = TextArea(
            prompt="> ",
            multiline=False,
            wrap_lines=False,
            history=self._history,
            completer=SlashCommandCompleter(),
            complete_while_typing=True,
            style="class:input",
        )

        body = HSplit(
            [
                self.transcript,
                Window(
                    height=1,
                    content=FormattedTextControl(self._get_status_bar_text),
                ),
                self.input,
            ]
        )

        layout = FloatContainer(
            content=body,
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=8),
                )
            ],
        )

        self.app = Application(
            layout=Layout(layout, focused_element=self.input),
            full_screen=True,
            mouse_support=False,
            style=APP_STYLE,
            key_bindings=self._build_key_bindings(),
            clipboard=WindowsClipboard(),
        )

    def _build_key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("enter")
        def _(event):
            buffer = self.input.buffer
            if buffer.complete_state and buffer.complete_state.current_completion:
                buffer.apply_completion(buffer.complete_state.current_completion)
                return

            if self.has_selection():
                if self._pending_input is not None and not self._pending_input.done():
                    self._pending_input.set_result("__select__")
                buffer.set_document(Document("", 0), bypass_readonly=True)
                return

            text = buffer.text.strip()
            if not text or self._pending_input is None or self._pending_input.done():
                return

            self._pending_input.set_result(text)
            buffer.set_document(Document("", 0), bypass_readonly=True)

        @bindings.add("tab")
        def _(event):
            if self.app.layout.has_focus(self.input):
                self.app.layout.focus(self.transcript)
                self.set_status("Transcript focus. Ctrl+A copies all, Ctrl+Space starts selection, Tab returns.")
            else:
                self.app.layout.focus(self.input)
                self.set_status("")

        @bindings.add("/")
        def _(event):
            if not self.app.layout.has_focus(self.input):
                self.app.layout.focus(self.input)
            buffer = self.input.buffer
            buffer.insert_text("/")
            if buffer.text == "/":
                buffer.start_completion(select_first=True)

        @bindings.add("up")
        def _(event):
            if self.has_selection():
                self._selection_index = (self._selection_index - 1) % len(self._selection_options)
                self._render_transcript()
                return
            event.app.current_buffer.auto_up()

        @bindings.add("down")
        def _(event):
            if self.has_selection():
                self._selection_index = (self._selection_index + 1) % len(self._selection_options)
                self._render_transcript()
                return
            event.app.current_buffer.auto_down()

        @bindings.add("pageup")
        def _(event):
            self.app.layout.focus(self.transcript)
            self.transcript.buffer.cursor_up(count=15)
            self.set_status("Scrolling transcript. Tab returns to input.")

        @bindings.add("pagedown")
        def _(event):
            self.app.layout.focus(self.transcript)
            self.transcript.buffer.cursor_down(count=15)
            self.set_status("Scrolling transcript. Tab returns to input.")

        @bindings.add("escape", "up")
        def _(event):
            self.app.layout.focus(self.transcript)
            self.transcript.buffer.cursor_up(count=3)
            self.set_status("Scrolling transcript. Tab returns to input.")

        @bindings.add("escape", "down")
        def _(event):
            self.app.layout.focus(self.transcript)
            self.transcript.buffer.cursor_down(count=3)
            self.set_status("Scrolling transcript. Tab returns to input.")

        @bindings.add("home")
        def _(event):
            self.app.layout.focus(self.transcript)
            self.transcript.buffer.cursor_position = 0
            self.set_status("Top of transcript. Tab returns to input.")

        @bindings.add("end")
        def _(event):
            self.app.layout.focus(self.transcript)
            self.transcript.buffer.cursor_position = len(self.transcript.buffer.text)
            self.set_status("Bottom of transcript. Tab returns to input.")

        @bindings.add("escape")
        def _(event):
            if self.has_selection():
                self.cancel_selection()
                if self._pending_input is not None and not self._pending_input.done():
                    self._pending_input.set_result("__cancel_select__")

        @bindings.add("c-v")
        def _(event):
            if not self.app.layout.has_focus(self.input):
                self.app.layout.focus(self.input)
            data = event.app.clipboard.get_data()
            if data.text:
                self.input.buffer.insert_text(data.text)

        @bindings.add("c-c")
        def _(event):
            buffer = event.app.current_buffer
            if buffer.selection_state:
                event.app.clipboard.set_data(buffer.copy_selection())
                if self.app.layout.has_focus(self.transcript):
                    self.set_status("Transcript selection copied.")
                return
            if self.has_selection():
                self.cancel_selection()
                if self._pending_input is not None and not self._pending_input.done():
                    self._pending_input.set_result("__cancel_select__")
                return
            if self._pending_input is not None and not self._pending_input.done():
                self._pending_input.set_exception(EOFError())

        @bindings.add("c-space")
        def _(event):
            if self.app.layout.has_focus(self.transcript):
                buffer = self.transcript.buffer
                if buffer.selection_state:
                    buffer.exit_selection()
                    self.set_status("Transcript selection cleared.")
                else:
                    buffer.start_selection()
                    self.set_status("Transcript selection started. Move with arrows, Ctrl+C copies.")

        @bindings.add("c-a")
        def _(event):
            if self.app.layout.has_focus(self.transcript):
                buffer = self.transcript.buffer
                event.app.clipboard.set_data(ClipboardData(buffer.text))
                self.set_status("Transcript copied to clipboard.")
                return
            event.app.current_buffer.cursor_position = 0

        @bindings.add("c-q")
        @bindings.add("c-d")
        def _(event):
            if self._pending_input is not None and not self._pending_input.done():
                self._pending_input.set_exception(EOFError())

        return bindings

    def _get_status_bar_text(self):
        return [("class:status", f" {self._status}" if self._status else "")]

    def _selection_block(self) -> str:
        if not self._selection_options:
            return ""

        lines = [self._selection_title]
        for index, option in enumerate(self._selection_options):
            prefix = ">" if index == self._selection_index else " "
            lines.append(f"{prefix} {index + 1}. {option['label']}  [{option['thread_id'][:8]}]")
        if self._selection_instruction:
            lines.append(self._selection_instruction)
        return "\n".join(lines)

    def _render_transcript(self):
        previous_position = self.transcript.buffer.cursor_position
        was_at_bottom = previous_position >= len(self.transcript.buffer.text)
        text = self._transcript_text
        selection_block = self._selection_block()
        if selection_block:
            if text:
                text += "\n\n"
            text += selection_block
        if self.app.layout.has_focus(self.transcript) and not was_at_bottom:
            cursor_position = min(previous_position, len(text))
        else:
            cursor_position = len(text)
        self.transcript.buffer.set_document(
            Document(text, cursor_position=cursor_position),
            bypass_readonly=True,
        )
        self.app.invalidate()

    def append_block(self, text: str):
        if self._transcript_text:
            self._transcript_text += "\n"
        self._transcript_text += text.rstrip() + "\n"
        self._render_transcript()

    def clear_transcript(self):
        self._transcript_text = ""
        self._stream_anchor = None
        self._render_transcript()

    def has_selection(self) -> bool:
        return bool(self._selection_options)

    def start_selection(self, title: str, options: list[dict], instruction: str):
        self._selection_title = title
        self._selection_options = options
        self._selection_index = 0
        self._selection_instruction = instruction
        self.input.buffer.set_document(Document("", 0), bypass_readonly=True)
        self._render_transcript()

    def cancel_selection(self):
        self._selection_title = ""
        self._selection_options = []
        self._selection_index = 0
        self._selection_instruction = ""
        self._render_transcript()

    def current_selection(self):
        if not self._selection_options:
            return None
        return self._selection_options[self._selection_index]

    def set_status(self, text: str):
        self._status = text
        self.app.invalidate()

    def start_bot_message(self):
        if self._transcript_text and not self._transcript_text.endswith("\n"):
            self._transcript_text += "\n"
        self._stream_anchor = len(self._transcript_text)
        self._transcript_text += "Bot:\n"
        self._render_transcript()

    def update_bot_message(self, text: str):
        if self._stream_anchor is None:
            self.start_bot_message()
        self._transcript_text = self._transcript_text[: self._stream_anchor] + f"Bot:\n{text}\n"
        self._render_transcript()

    def finish_bot_message(self, text: str):
        self.update_bot_message(text)
        self._stream_anchor = None

    async def prompt(self) -> str:
        loop = asyncio.get_running_loop()
        self._pending_input = loop.create_future()
        self.app.layout.focus(self.input)
        return await self._pending_input

    async def run(self, worker):
        self.app.create_background_task(worker())
        await self.app.run_async()

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

async def stream_response(graph, user_input: str, config: dict, ui: ChatUI) -> str:
    full_text = ""
    ui.start_bot_message()

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
            if not full_text:
                ui.set_status("")
            full_text += chunk.content
            ui.update_bot_message(full_text)

    if not full_text:
        full_text = "No response received. Check your API key in settings.json."

    ui.finish_bot_message(full_text)
    return full_text


# ──────────────────────────────────────────
# Main
# ──────────────────────────────────────────

async def run():
    os.makedirs(DATA_DIR, exist_ok=True)
    session = create_chat_session()

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

            ui = ChatUI()
            config = start_new_conversation()
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
                            transcript = _render_messages(messages)
                            if transcript:
                                ui.append_block(transcript)
                        ui.append_block(
                            "Resumed session: "
                            + _format_checkpoint_time(selected["ts"])
                            + f"  ({selected['thread_id'][:8]})"
                        )
                        continue

                    ui.append_block(f"You: {user_input}")

                    if user_input == "/exit":
                        ui.append_block("Bye!")
                        ui.app.exit()
                        break

                    elif user_input == "/help":
                        lines = ["Available commands:"]
                        for cmd, desc in COMMANDS.items():
                            lines.append(f"  {cmd}  -  {desc}")
                        ui.append_block("\n".join(lines))

                    elif user_input == "/settings":
                        s = load_settings()
                        lines = ["Current settings:"]
                        for k, v in s.items():
                            display = v[:6] + "..." if k == "api_key" and len(v) > 6 else v
                            lines.append(f"  {k}: {display}")
                        ui.append_block("\n".join(lines))

                    elif user_input == "/new":
                        config = start_new_conversation()
                        ui.clear_transcript()
                        ui.append_block("New conversation started. Type /help for commands.")

                    elif user_input == "/resume":
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

                    # elif user_input == "/memory":
                    #     await show_memory(store, user_id)

                    elif user_input.startswith("/"):
                        ui.append_block(f"Unknown command: {user_input}. Type /help.")

                    else:
                        ui.set_status(random.choice(STATUS_MESSAGES))
                        try:
                            await stream_response(graph, user_input, config, ui)
                        finally:
                            ui.set_status("")

            await ui.run(chat_loop)


if __name__ == "__main__":
    asyncio.run(run())
