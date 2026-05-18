import asyncio
import time

from prompt_toolkit import PromptSession #Session management.
from prompt_toolkit.application import Application #Application management.
from prompt_toolkit.clipboard import ClipboardData #Used for copy-paste support.
from prompt_toolkit.completion import Completer, Completion #Used for autocomplete. e.g /he<TAB> >/help
from prompt_toolkit.document import Document #Document management.
from prompt_toolkit.history import InMemoryHistory #History management.
from prompt_toolkit.key_binding import KeyBindings #Custom keyboard shortcuts.
from prompt_toolkit.keys import Keys #Special keyboard keys.
from prompt_toolkit.layout import HSplit, Layout, Window #Used to design UI layout.
from prompt_toolkit.layout.containers import Float, FloatContainer #Floating popup menus used for autocomplete dropdown.
from prompt_toolkit.layout.controls import FormattedTextControl #Used to display formatted text.
from prompt_toolkit.layout.menus import CompletionsMenu #Autocomplete popup UI.
from prompt_toolkit.layout.processors import Processor, Transformation #Used to process and transform text.
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.widgets import TextArea #Used to display text.

from chatbot_cli.app_config import APP_STYLE, COMMANDS
from chatbot_cli.clipboard import WindowsClipboard #Used for copy-paste support.
from chatbot_cli.formatting import format_ai_output #Used to format AI output.


class SlashCommandCompleter(Completer):
    """Show slash commands only while typing a command at the prompt."""

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor #Gets current input before cursor e.g. /he
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


class UserLineHighlighter(Processor):
    """Highlight transcript lines that represent user messages."""

    def apply_transformation(self, transformation_input):
        fragments = transformation_input.fragments
        line_text = "".join(text for _, text, *_ in fragments)
        if line_text.startswith("> "):
            line_width = len(line_text)
            pad = max(0, transformation_input.width - line_width)
            styled_line = line_text + (" " * pad)
            return Transformation(
                [("class:user-line", styled_line)],
                source_to_display=lambda i: i,
                display_to_source=lambda i: min(i, line_width),
            )
        return Transformation(fragments)


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


class ChatUI:
    def __init__(self):
        self._history = InMemoryHistory()
        self._transcript_text = ""
        self._pending_input = None
        self._stream_anchor = None
        self._status = ""
        self._base_status = ""
        self._spinner_index = 0
        self._spinner_active = False
        self._spinner_task = None
        self._selection_options = []
        self._selection_index = 0
        self._selection_title = ""
        self._selection_instruction = ""
        self._ctrl_c_armed_until = 0.0

        self.transcript = TextArea(
            text="",
            read_only=True,
            focusable=True,
            focus_on_click=True,
            scrollbar=True,
            wrap_lines=True,
            style="class:transcript",
            input_processors=[UserLineHighlighter()],
        )
        self._transcript_mouse_handler = self.transcript.control.mouse_handler
        self.transcript.control.mouse_handler = self._handle_transcript_mouse_event
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
            mouse_support=True,
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
                self.set_status("Transcript focus. Mouse wheel/PageUp/PageDown scroll, Ctrl+A copies all, Tab returns.")
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
            if self.app.layout.has_focus(self.transcript):
                self._scroll_transcript(-1)
                return
            event.app.current_buffer.auto_up()

        @bindings.add("down")
        def _(event):
            if self.has_selection():
                self._selection_index = (self._selection_index + 1) % len(self._selection_options)
                self._render_transcript()
                return
            if self.app.layout.has_focus(self.transcript):
                self._scroll_transcript(1)
                return
            event.app.current_buffer.auto_down()

        @bindings.add("pageup")
        def _(event):
            self._scroll_transcript(-self._page_scroll_count())

        @bindings.add("pagedown")
        def _(event):
            self._scroll_transcript(self._page_scroll_count())

        @bindings.add("escape", "up")
        def _(event):
            self._scroll_transcript(-3)

        @bindings.add("escape", "down")
        def _(event):
            self._scroll_transcript(3)

        @bindings.add(Keys.ScrollUp)
        def _(event):
            self._scroll_transcript(-3)

        @bindings.add(Keys.ScrollDown)
        def _(event):
            self._scroll_transcript(3)

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
            now = time.monotonic()
            if now < self._ctrl_c_armed_until:
                if self._pending_input is not None and not self._pending_input.done():
                    self._pending_input.set_exception(EOFError())
                return
            self._ctrl_c_armed_until = now + 2.5
            self._status = [("fg:#aaaaaa", "Press Ctrl-C again to exit")]
            self.app.invalidate()

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
        if isinstance(self._status, list):
            return self._status
        spinner = ["|", "/", "-", "\\"][self._spinner_index % 4] if self._spinner_active else ""
        return [("class:status", f" {spinner} {self._status}" if self._status else "")]

    def _page_scroll_count(self) -> int:
        info = self.transcript.window.render_info
        if info is None:
            return 15
        return max(1, info.window_height - 2)

    def _scroll_transcript(self, amount: int):
        self.app.layout.focus(self.transcript)
        buffer = self.transcript.buffer
        if amount > 0:
            buffer.cursor_down(count=amount)
        elif amount < 0:
            buffer.cursor_up(count=-amount)
        self.set_status("Scrolling transcript. Mouse wheel/PageUp/PageDown move history, Tab returns to input.")
        self.app.invalidate()

    def _handle_transcript_mouse_event(self, mouse_event):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self._scroll_transcript(-3)
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self._scroll_transcript(3)
            return None
        return self._transcript_mouse_handler(mouse_event)

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
        self._transcript_text += text.strip("\n") + "\n"
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
        self._base_status = text
        if text:
            if not self._spinner_active:
                self._spinner_active = True
                if self._spinner_task is None or self._spinner_task.done():
                    self._spinner_task = asyncio.create_task(self._run_spinner())
            self.app.invalidate()
        else:
            self._spinner_active = False
            if self._spinner_task is not None:
                self._spinner_task.cancel()
                self._spinner_task = None
            self.app.invalidate()

    async def _run_spinner(self):
        try:
            while self._spinner_active:
                self._spinner_index += 1
                self.app.invalidate()
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    def start_bot_message(self):
        if self._transcript_text and not self._transcript_text.endswith("\n"):
            self._transcript_text += "\n"
        self._stream_anchor = len(self._transcript_text)
        self._transcript_text += "* "
        self._render_transcript()

    def update_bot_message(self, text: str):
        if self._stream_anchor is None:
            self.start_bot_message()
        self._transcript_text = self._transcript_text[: self._stream_anchor] + format_ai_output(text) + "\n"
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
