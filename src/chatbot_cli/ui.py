import asyncio
import time
import random

from prompt_toolkit import PromptSession
from prompt_toolkit.application import Application
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.containers import Float, FloatContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import Processor, Transformation
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.selection import SelectionType

from chatbot_cli.app_config import APP_STYLE, COMMANDS
from chatbot_cli.clipboard import WindowsClipboard
from chatbot_cli.formatting import format_ai_output

# Dynamic status messages for the AI thinking phase
STATUS_MESSAGES = [
    "Thinking...",
    "Planning...",
    "Reasoning...",
    "Analyzing context...",
    "Writing response...",
    "Connecting ideas...",
    "Processing...",
    "Building answer...",
]

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


class TranscriptProcessor(Processor):
    """Highlights different types of lines in the transcript."""

    def apply_transformation(self, transformation_input):
        fragments = transformation_input.fragments
        line_text = "".join(text for _, text, *_ in fragments)

        if line_text.startswith("> "):
            # USER MESSAGE: Pad with spaces to make the highlight span the complete row
            pad_length = max(0, transformation_input.width - len(line_text))
            styled_line = line_text + (" " * pad_length)
            
            return Transformation(
                [("class:user-line", styled_line)],
                source_to_display=lambda i: i,
                display_to_source=lambda i: min(i, len(line_text)),
            )
            
        elif line_text[:1] in ["\u200c", "\u200d", "\u200e", "\u200f", "\u202a", "\u202b"]:
            gradient_map = {
                "\u200c": "fg:#fff5a0",  # soft yellow
                "\u200d": "fg:#ffe066",  # warm yellow
                "\u200e": "fg:#ffcc33",  # golden
                "\u200f": "fg:#ffb000",  # amber
                "\u202a": "fg:#ff9500",  # orange
                "\u202b": "fg:#ff7a00",  # deep orange
            }

            marker = line_text[:1]
            clean_text = line_text[1:]

            return Transformation([
                (gradient_map.get(marker, "fg:#ffffff"), clean_text)
            ])
            
        elif line_text.startswith("⏱"):
            # Timing messages (Orange)
            return Transformation([("fg:#ffaa00", line_text)])

        # Default text (LLM Output)
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
        
        self._chunks = []  
        self._tool_blocks = []   
        self._tool_expanded = set()  
        
        self._pending_input = None
        self._status = ""
        self._base_status = ""
        self._status_display = ""
        self._spinner_index = 0
        self._spinner_active = False
        self._spinner_task = None
        self._turn_start_time = None 
        
        self.model_name = "Mistral" 
        
        self._selection_options = []
        self._selection_index = 0
        self._selection_title = ""
        self._selection_instruction = ""
        self._ctrl_c_armed_until = 0.0
        self._auto_scroll = True

        self.transcript = TextArea(
            text="",
            read_only=True,
            focusable=False,
            focus_on_click=False,  
            scrollbar=True,
            wrap_lines=True,
            style="class:transcript",
            input_processors=[TranscriptProcessor()],
        )
        
        self._transcript_mouse_handler = self.transcript.control.mouse_handler
        self.transcript.control.mouse_handler = self._handle_transcript_mouse_event
        
        self.input = TextArea(
            prompt=[("fg:#ffaa00 bold", "> ")],
            multiline=True, 
            height=lambda: min(6, self.input.document.line_count),       
            wrap_lines=True,
            history=self._history,
            completer=SlashCommandCompleter(),
            complete_while_typing=True,
            style="class:input",
        )

        body = HSplit(
            [
                self.transcript,
                Window(height=1, char="─", style="fg:#444444"), 
                self.input,                                     
                Window(height=1, char="─", style="fg:#444444"), 
                Window(height=1, content=FormattedTextControl(self._get_status_bar_text)), 
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

    def set_model_name(self, name: str):
        """Allows app.py to dynamically update the model name shown in the footer."""
        self.model_name = name
        self.app.invalidate()

    def _build_key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("enter")
        def _(event):
            self._auto_scroll = True 
            
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
                self.set_status("Transcript focused. Scroll with arrows/PgUp/PgDn. Tab returns.")
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

        @bindings.add("home")
        def _(event):
            self._auto_scroll = False
            self.transcript.buffer.cursor_position = 0
            self.app.invalidate()

        @bindings.add("end")
        def _(event):
            self._auto_scroll = True
            self._render_transcript()

        @bindings.add("escape")
        def _(event):
            if self.has_selection():
                self.cancel_selection()
                if self._pending_input is not None and not self._pending_input.done():
                    self._pending_input.set_result("__cancel_select__")

        @bindings.add("c-space")
        def _(event):
            """Start keyboard selection mode to allow copying text."""
            buffer = event.app.current_buffer
            if buffer.selection_state:
                buffer.exit_selection()
                self.set_status("Selection cleared.")
            else:
                buffer.start_selection(selection_type=SelectionType.CHARACTERS)
                self.set_status("Selection started. Move arrows to highlight, Ctrl+C to copy.")

        @bindings.add("c-c")
        def _(event):
            buffer = event.app.current_buffer

            # 1. If text is highlighted (via Ctrl+Space), copy it
            if buffer.selection_state:
                try:
                    data = buffer.copy_selection()
                    event.app.clipboard.set_data(data)
                    self.set_status("Copied to clipboard!")
                    buffer.exit_selection()
                    self.app.invalidate()
                except Exception as e:
                    self.set_status(f"Copy failed: {e}")
                    buffer.exit_selection()
                return

            # 2. If no text is highlighted, double-press to exit
            now = time.monotonic()
            if now < self._ctrl_c_armed_until:
                if self._pending_input is not None and not self._pending_input.done():
                    self._pending_input.set_exception(EOFError())
                return
            self._ctrl_c_armed_until = now + 2.5
            self._status = [("fg:#aaaaaa", "Press Ctrl-C again to exit")]
            self.app.invalidate()

        @bindings.add("c-v")
        def _(event):
            """Handle pasting text into the input field."""
            if not self.app.layout.has_focus(self.input):
                self.app.layout.focus(self.input)
            data = event.app.clipboard.get_data()
            if data.text:
                self.input.buffer.insert_text(data.text)

        @bindings.add("c-t")
        def _(event):
            if not self._tool_blocks:
                return
            last_idx = len(self._tool_blocks) - 1
            if last_idx in self._tool_expanded:
                self._tool_expanded.discard(last_idx)
                self.set_status("Tool output collapsed.")
            else:
                self._tool_expanded.add(last_idx)
                self.set_status("Tool output expanded. Ctrl+T to collapse.")
            self._rebuild_transcript()

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
        
        if self._spinner_active or self._status_display:
            return [
                ("fg:#ffaa00 bold", f" {spinner} ▶▶ " if spinner else " ▶▶ "),
                ("fg:#ffaa00", self._status_display)
            ]
            
        return [
            ("fg:#ffaa00 bold", " ▶▶ "),
            ("fg:#888888", f"{self.model_name} | Ctrl+T: Toggle | Ctrl+C x2: Exit")
        ]

    def _page_scroll_count(self) -> int:
        info = self.transcript.window.render_info
        if info is None:
            return 15
        return max(1, info.window_height - 2)

    def _scroll_transcript(self, amount: int):
        buffer = self.transcript.buffer
        doc = buffer.document
        
        if amount < 0:
            self._auto_scroll = False
            for _ in range(-amount):
                buffer.cursor_position += doc.get_cursor_up_position()
        else:
            for _ in range(amount):
                buffer.cursor_position += doc.get_cursor_down_position()

        if buffer.cursor_position >= len(buffer.text) - 1:
            self._auto_scroll = True

        self.app.invalidate()

    def _handle_transcript_mouse_event(self, mouse_event):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self._scroll_transcript(-3)
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self._scroll_transcript(3)
            return None
        result = self._transcript_mouse_handler(mouse_event)
        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            self.app.layout.focus(self.input)
        return result

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
        text = self._transcript_text
        selection_block = self._selection_block()

        if selection_block:
            if text:
                text += "\n\n"
            text += selection_block

        buffer = self.transcript.buffer
        prev_cursor = buffer.cursor_position

        new_cursor = len(text) if self._auto_scroll else min(prev_cursor, len(text))

        buffer.set_document(
            Document(text, cursor_position=new_cursor),
            bypass_readonly=True,
        )
        self.app.invalidate()

    # ─────────────────────────────────────────────────────────────────
    # CHUNKED TRANSCRIPT LOGIC
    # ─────────────────────────────────────────────────────────────────

    def _rebuild_transcript(self):
        text = ""
        for chunk in self._chunks:
            if chunk['type'] == 'text':
                text += chunk['text'] + "\n"
            elif chunk['type'] == 'tool':
                idx = chunk['idx']
                tb = self._tool_blocks[idx]
                text += self._tool_block_text(idx, tb['name'], tb['output'], tb['in_flight'])
            elif chunk['type'] == 'bot':
                text += chunk['text'] + "\n"
            elif chunk['type'] == 'time':
                text += chunk['text'] + "\n\n"

        self._transcript_text = text
        self._render_transcript()

    def append_block(self, text: str):
        self._chunks.append({'type': 'text', 'text': text.strip('\n')})
        self._rebuild_transcript()

    def clear_transcript(self):
        self._chunks.clear()
        self._tool_blocks.clear()
        self._tool_expanded.clear()
        self._auto_scroll = True
        self._rebuild_transcript()

    def start_bot_message(self):
        self._turn_start_time = time.time()
        
        self._spinner_active = True
        if self._spinner_task is None or self._spinner_task.done():
            self._spinner_task = asyncio.create_task(self._run_spinner())
            
        self._chunks.append({'type': 'bot', 'text': '* '})
        self._rebuild_transcript()

    def update_bot_message(self, text: str):
        if not self._chunks or self._chunks[-1]['type'] != 'bot':
            self.start_bot_message()
        self._chunks[-1]['text'] = '* ' + format_ai_output(text)
        self._rebuild_transcript()

    def finish_bot_message(self, text: str):
        self.update_bot_message(text)
        
        if self._turn_start_time:
            elapsed = time.time() - self._turn_start_time
            self._turn_start_time = None
            self._chunks.append({'type': 'time', 'text': f"⏱  Total time: ({elapsed:.1f}s)"})
            self._rebuild_transcript()
            
        self.set_status("") 

    def append_tool_block(self, tool_name: str, full_output: str, in_flight: bool = False) -> int:
        idx = len(self._tool_blocks)
        self._tool_blocks.append({'name': tool_name, 'output': full_output, 'in_flight': in_flight})
        self._chunks.append({'type': 'tool', 'idx': idx})
        self._rebuild_transcript()
        return idx

    def update_tool_block(self, idx: int, full_output: str, in_flight: bool = True):
        if 0 <= idx < len(self._tool_blocks):
            self._tool_blocks[idx]['output'] = full_output
            self._tool_blocks[idx]['in_flight'] = in_flight
            self._rebuild_transcript()

    def _tool_block_text(self, idx: int, tool_name: str, full_output: str, in_flight: bool) -> str:
        lines = full_output.rstrip().splitlines()
        first_line = lines[0] if lines else tool_name
        
        header = f"\u200b┌ 🔧 {first_line}"
        expanded = idx in self._tool_expanded

        def format_body(lines_list):
            if not lines_list:
                return "\u200b  (No output)"
            return "\n".join(f"\u200b  {l}" for l in lines_list)

        if not in_flight and not expanded:
            return f"\n{header}  [✓]\n\u200b└{'─' * 24}\n"
            
        if not in_flight and expanded:
            body_lines = lines[1:] if len(lines) > 1 else []
            body = format_body(body_lines)
            hint = "\u200b\\ Tool output expanded. Ctrl+T to collapse."
            return f"\n{header}  [✓]\n{body}\n{hint}\n"

        if expanded:
            body_lines = lines[1:] if len(lines) > 1 else []
            body = format_body(body_lines) if body_lines else "\u200b  (Waiting for output...)"
            hint = "\u200b\\ Tool output expanded. Ctrl+T to collapse."
        else:
            body = "\u200b  Running..."
            hint = "\u200b\\ Press Ctrl+T to see whole output."

        return f"\n{header}\n{body}\n{hint}\n"

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
            self._status_display = ""
            if self._spinner_task is not None:
                self._spinner_task.cancel()
                self._spinner_task = None
            self.app.invalidate()

    async def _run_spinner(self):
        try:
            ticks = 0
            current_msg = random.choice(STATUS_MESSAGES)
            
            while self._spinner_active:
                self._spinner_index += 1
                ticks += 1
                
                if ticks % 15 == 0:
                    current_msg = random.choice(STATUS_MESSAGES)
                
                if self._base_status:
                    self._status_display = self._base_status
                else:
                    self._status_display = current_msg

                self.app.invalidate()
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    async def prompt(self) -> str:
        loop = asyncio.get_running_loop()
        self._pending_input = loop.create_future()
        self.app.layout.focus(self.input)
        return await self._pending_input

    async def run(self, worker):
        self.app.create_background_task(worker())
        try:
            await self.app.run_async()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            # Surface unexpected TUI-level errors without crashing silently
            raise RuntimeError(f"ChatUI crashed unexpectedly: {e}") from e