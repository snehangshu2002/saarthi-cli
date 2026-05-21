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
from prompt_toolkit.mouse_events import MouseEventType, MouseButton
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.selection import SelectionType
from prompt_toolkit.layout.mouse_handlers import MouseHandlers
from prompt_toolkit.filters import has_focus

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

# Unicode markers for semantic line types to bypass regex-based styling
THOUGHT_BODY_MARKER = "\u2001"
TOOL_BODY_MARKER = "\u2002"
THOUGHT_HEADER_MARKER = "\u2003"
TOOL_HEADER_MARKER = "\u2004"
HINT_MARKER = "\u2005"

def get_friendly_tool_name(name: str) -> str:
    """Map raw tool names to clean, user-friendly display names."""
    mapping = {
        "duckduckgo_search": "Search",
        "tavily_search_results_json": "Search",
        "tavily_search": "Search",
    }
    return mapping.get(name, name)

# Global tracking of active TUI
ACTIVE_CHAT_UI = None


def _grab_clipboard_image():
    """
    Try to get an image from the Windows clipboard.
    Returns (filepath: str, filename: str) on success, or (None, error_msg: str) on failure.

    Handles three cases:
      1. PIL.Image   — image data directly in clipboard (screenshot, copy from browser/viewer)
      2. list        — file paths in clipboard (image file copied from Explorer)
      3. None / other — no image in clipboard
    """
    import datetime
    from pathlib import Path
    from chatbot_cli.app_config import USER_DATA_DIR

    try:
        from PIL import ImageGrab, Image

        img = ImageGrab.grabclipboard()

        # ── Case 1: actual pixel data ──────────────────────────────────────
        if isinstance(img, Image.Image):
            images_dir = USER_DATA_DIR / "images"
            images_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"copied_image_{timestamp}.png"
            filepath = images_dir / filename
            img.save(filepath, "PNG")
            return str(filepath), filename

        # ── Case 2: list of file paths (copied from Explorer) ─────────────
        if isinstance(img, list):
            IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif",
                          ".webp", ".tiff", ".tif", ".ico"}
            for item in img:
                p = Path(str(item))
                if p.suffix.lower() in IMAGE_EXTS and p.exists():
                    images_dir = USER_DATA_DIR / "images"
                    images_dir.mkdir(parents=True, exist_ok=True)
                    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"copied_image_{timestamp}{p.suffix.lower()}"
                    dest = images_dir / filename
                    import shutil
                    shutil.copy2(str(p), str(dest))
                    return str(dest), filename
            # list contained no image files
            return None, ""

        # ── Case 3: None / non-image clipboard content ─────────────────────
        return None, ""

    except Exception as e:
        return None, f"Clipboard image error: {e}"

# Monkey-patch MouseHandlers.set_mouse_handler_for_range to intercept all mouse events globally.
original_set_mouse_handler_for_range = MouseHandlers.set_mouse_handler_for_range

def new_set_mouse_handler_for_range(self, x_min, x_max, y_min, y_max, handler):
    import sys
    caller_self = None
    try:
        caller_self = sys._getframe(1).f_locals.get('self')
    except Exception:
        pass

    def wrapped_handler(mouse_event):
        if not ACTIVE_CHAT_UI:
            return handler(mouse_event)

        # 1. Universal mouse scroll anywhere scrolls the transcript
        if mouse_event.event_type in (MouseEventType.SCROLL_UP, MouseEventType.SCROLL_DOWN):
            amount = -3 if mouse_event.event_type == MouseEventType.SCROLL_UP else 3
            ACTIVE_CHAT_UI._scroll_transcript(amount)
            return None

        # 2. Right-click copy/paste globally
        if mouse_event.event_type == MouseEventType.MOUSE_DOWN and mouse_event.button == MouseButton.RIGHT:
            if ACTIVE_CHAT_UI.transcript.buffer.selection_state:
                try:
                    data = ACTIVE_CHAT_UI.transcript.buffer.copy_selection()
                    ACTIVE_CHAT_UI.app.clipboard.set_data(data)
                    ACTIVE_CHAT_UI.set_status("Copied to clipboard!")
                except Exception as e:
                    ACTIVE_CHAT_UI.set_status(f"Copy failed: {e}", show_spinner=False)
                ACTIVE_CHAT_UI.transcript.buffer.exit_selection()
                ACTIVE_CHAT_UI.app.layout.focus(ACTIVE_CHAT_UI.input)
            else:
                filepath, filename = _grab_clipboard_image()
                if filepath:
                    ACTIVE_CHAT_UI.pasted_images.append(filepath)
                    ACTIVE_CHAT_UI.input.buffer.insert_text(f" [Image Pasted: {filename}] ")
                    ACTIVE_CHAT_UI.set_status(f"Image pasted: {filename}")
                    ACTIVE_CHAT_UI.app.layout.focus(ACTIVE_CHAT_UI.input)
                    ACTIVE_CHAT_UI.app.invalidate()
                    return None
                elif filename:  # non-empty means an error string was returned
                    ACTIVE_CHAT_UI.set_status(filename, show_spinner=False)
                else:
                    # No image — fall back to text paste
                    data = ACTIVE_CHAT_UI.app.clipboard.get_data()
                    if data and data.text:
                        ACTIVE_CHAT_UI.input.buffer.insert_text(data.text)
                ACTIVE_CHAT_UI.app.layout.focus(ACTIVE_CHAT_UI.input)
            ACTIVE_CHAT_UI.app.invalidate()
            return None

        # 3. Left-click down on transcript focuses transcript control to allow drag selection
        if mouse_event.event_type == MouseEventType.MOUSE_DOWN and mouse_event.button == MouseButton.LEFT:
            if caller_self == ACTIVE_CHAT_UI.transcript.window:
                ACTIVE_CHAT_UI.app.layout.current_control = ACTIVE_CHAT_UI.transcript.control
            else:
                # Clicking elsewhere clears the selection
                ACTIVE_CHAT_UI.transcript.buffer.exit_selection()
                ACTIVE_CHAT_UI.app.invalidate()

        # Run original mouse handler
        result = handler(mouse_event)

        # 4. Left-click up on transcript focuses input if no selection was made
        if mouse_event.event_type == MouseEventType.MOUSE_UP and mouse_event.button == MouseButton.LEFT:
            if caller_self == ACTIVE_CHAT_UI.transcript.window:
                if not ACTIVE_CHAT_UI.transcript.buffer.selection_state:
                    ACTIVE_CHAT_UI.app.layout.focus(ACTIVE_CHAT_UI.input)

        return result

    original_set_mouse_handler_for_range(self, x_min, x_max, y_min, y_max, wrapped_handler)

MouseHandlers.set_mouse_handler_for_range = new_set_mouse_handler_for_range


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

    def __init__(self, ui_instance):
        super().__init__()
        self.ui = ui_instance

    def apply_transformation(self, transformation_input):
        fragments = transformation_input.fragments
        line_text = "".join(text for _, text, *_ in fragments)

        # Check first character for custom formatting markers
        marker = line_text[:1]
        if marker in ("\u2001", "\u2002", "\u2003", "\u2004", "\u2005"):
            clean_text = line_text[1:]
            
            if marker == "\u2003":  # Thought Header
                return Transformation([
                    ("fg:#ff8c00 bold", "▸ "),
                    ("fg:#ffaa00 bold", clean_text[2:])
                ])
            elif marker == "\u2001":  # Thought Body
                return Transformation([("fg:#888888 italic", clean_text)])
                
            elif marker == "\u2004":  # Tool Header
                idx = clean_text.find("(")
                if idx != -1:
                    tool_name = clean_text[2:idx]
                    rest = clean_text[idx:]
                    
                    # Detect collapsed or expanded hint inline in tool header
                    hint_suffix = ""
                    for hint in (" (ctrl+o to expand)", " (ctrl+o to collapse)"):
                        if hint in rest:
                            rest = rest.replace(hint, "")
                            hint_suffix = hint
                            break
                            
                    fragments = [
                        ("fg:#00aaff bold", "● "),
                        ("fg:#00ffff bold", tool_name),
                        ("fg:#cccccc", rest)
                    ]
                    if hint_suffix:
                        fragments.append(("fg:#555555 italic", hint_suffix))
                    return Transformation(fragments)
                return Transformation([
                    ("fg:#00aaff bold", "● "),
                    ("fg:#00ffff bold", clean_text[2:])
                ])
                
            elif marker == "\u2002":  # Tool Body
                first_char = clean_text[:1]
                if first_char in ("⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"):
                    return Transformation([
                        ("fg:#00ffff bold", "  " + first_char),
                        ("fg:#888888 italic", clean_text[1:])
                    ])
                elif "Tip: Press ctrl+g" in clean_text:
                    idx = clean_text.find("Tip:")
                    return Transformation([
                        ("fg:#555555", clean_text[:idx]),
                        ("fg:#888888 bold", "Tip:"),
                        ("fg:#555555 italic", clean_text[idx+4:])
                    ])
                elif "───" in clean_text:
                    return Transformation([("fg:#262626", clean_text)])
                    
                return Transformation([("fg:#bbbbbb", clean_text)])
                
            elif marker == "\u2005":  # Hint
                return Transformation([("fg:#666666 italic", clean_text)])

        # 1. BOT MESSAGE PREFIX: Highlight and style with Left-Border Track and dynamic provider theme color
        if line_text.startswith("❯ "):
            clean_text = line_text[2:]
            theme_color = self.ui._get_theme_color()
            return Transformation(
                [
                    ("fg:" + theme_color + " bold", "▌ "),
                    ("fg:" + theme_color + " bold", "Saarthi: "),
                    ("", clean_text)
                ],
                source_to_display=lambda i: 0 if i <= 1 else i + 9,
                display_to_source=lambda i: 0 if i < 11 else min(i - 9, len(line_text))
            )

        # 2. USER MESSAGE PREFIX: Left-Border track with Indigo/Purple accent style
        if line_text.startswith("> "):
            clean_text = line_text[2:]
            return Transformation(
                [
                    ("fg:#6366f1 bold", "▌ "),
                    ("fg:#818cf8 bold", "You: "),
                    ("", clean_text)
                ],
                source_to_display=lambda i: 0 if i <= 1 else i + 5,
                display_to_source=lambda i: 0 if i < 7 else min(i - 5, len(line_text))
            )
            
        elif line_text[:1] in ["\u200c", "\u200d", "\u200e", "\u200f", "\u202a", "\u202b"]:
            gradient_map = {
                "\u200c": "fg:#fff5a0",
                "\u200d": "fg:#ffe066",
                "\u200e": "fg:#ffcc33",
                "\u200f": "fg:#ffb000",
                "\u202a": "fg:#ff9500",
                "\u202b": "fg:#ff7a00",
            }
            marker = line_text[:1]
            clean_text = line_text[1:]
            return Transformation([(gradient_map.get(marker, "fg:#ffffff"), clean_text)])
            
        elif line_text.startswith("⏱"):
            return Transformation([("fg:#ffaa00", line_text)])

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
        global ACTIVE_CHAT_UI
        ACTIVE_CHAT_UI = self

        self._history = InMemoryHistory()
        self._transcript_text = ""
        
        self._chunks = []  
        self._tool_blocks = []   
        self._tool_expanded = set()  
        self._thought_blocks = []
        
        self._pending_input = None
        self._status = ""
        self._base_status = ""
        self._status_display = ""
        self._spinner_index = 0
        self._spinner_active = False
        self._spinner_task = None
        self._turn_start_time = None 
        self.pasted_images = []
        
        self.model_name = "Mistral" 
        
        self._selection_options = []
        self._selection_index = 0
        self._selection_title = ""
        self._selection_instruction = ""
        self._ctrl_c_armed_until = 0.0
        self._auto_scroll = True
        self.tool_approval_mode = "ask"  # Options: "ask", "auto"
        self.plan_mode = False

        self.transcript = TextArea(
            text="",
            read_only=True,
            focusable=True,
            focus_on_click=True,  
            scrollbar=True,
            wrap_lines=True,
            style="class:transcript",
            input_processors=[TranscriptProcessor(self)],
        )
        self.transcript.window.always_hide_cursor = lambda: True
        
        self.input = TextArea(
            prompt=self._get_prompt_text,
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
                Window(height=1, char="─", style="fg:#262626"), 
                self.input,                                     
                Window(height=1, char="─", style="fg:#262626"), 
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

        @bindings.add("enter", filter=has_focus(self.transcript))
        def _(event):
            buffer = self.transcript.buffer
            if buffer.selection_state:
                try:
                    data = buffer.copy_selection()
                    event.app.clipboard.set_data(data)
                    self.set_status("Copied to clipboard!")
                except Exception as e:
                    self.set_status(f"Copy failed: {e}", show_spinner=False)
                buffer.exit_selection()
            self.app.layout.focus(self.input)
            self.app.invalidate()

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

            # START CLOCK HERE: Captures full pipeline execution (Tools + LLM)
            self._turn_start_time = time.time()

            self._pending_input.set_result(text)
            buffer.set_document(Document("", 0), bypass_readonly=True)

        @bindings.add(Keys.Any, filter=has_focus(self.transcript))
        def _(event):
            # Intercept regular typed characters and direct them to input
            if event.data and not event.data.startswith('\x1b') and ord(event.data) >= 32:
                self.transcript.buffer.exit_selection()
                self.app.layout.focus(self.input)
                self.input.buffer.insert_text(event.data)

        @bindings.add("tab")
        def _(event):
            if self.app.layout.has_focus(self.input):
                self.app.layout.focus(self.transcript)
                self.set_status("Transcript focused. Scroll with arrows/PgUp/PgDn. Tab returns.")
            else:
                self.app.layout.focus(self.input)
                self.set_status("")

        @bindings.add("s-tab")
        def _(event):
            self.plan_mode = not self.plan_mode
            status = "ON" if self.plan_mode else "OFF"
            self.set_status(f"Plan Mode: {status} (Shift+Tab to toggle)", show_spinner=False)
            self.app.invalidate()

        @bindings.add("c-t")
        def _(event):
            if self.tool_approval_mode == "ask":
                self.tool_approval_mode = "auto"
                self.set_status("Tool approval: Auto-Approve (Ctrl+T to toggle)", show_spinner=False)
            else:
                self.tool_approval_mode = "ask"
                self.set_status("Tool approval: Ask (Ctrl+T to toggle)", show_spinner=False)
            self.app.invalidate()

        @bindings.add("c-g")
        def _(event):
            """Open external editor for long prompts."""
            if self.app.layout.has_focus(self.input):
                event.app.run_in_terminal(event.app.current_buffer.open_in_editor)

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
                    self.app.layout.focus(self.input)
                    self.app.invalidate()
                except Exception as e:
                    # Safely shows text without triggering an unwanted spinner
                    self.set_status(f"Copy failed: {e}", show_spinner=False)
                    buffer.exit_selection()
                    self.app.layout.focus(self.input)
                return

            # 2. If no text is highlighted, double-press to exit
            now = time.monotonic()
            if now < self._ctrl_c_armed_until:
                if self._pending_input is not None and not self._pending_input.done():
                    self._pending_input.set_exception(EOFError())
                return
            self._ctrl_c_armed_until = now + 2.5
            self._status = [("fg:" + self._get_theme_color() + " bold", "  ⚠  Press Ctrl-C again to exit")]
            self.app.invalidate()

        @bindings.add("c-v")
        def _(event):
            """Handle pasting text or images into the input field."""
            if not self.app.layout.has_focus(self.input):
                self.app.layout.focus(self.input)

            filepath, filename = _grab_clipboard_image()
            if filepath:
                self.pasted_images.append(filepath)
                self.input.buffer.insert_text(f" [Image Pasted: {filename}] ")
                self.set_status(f"Image pasted: {filename}")
                self.app.invalidate()
                return
            elif filename:  # non-empty error message
                self.set_status(filename, show_spinner=False)
                return

            # No image — fall back to text paste
            data = event.app.clipboard.get_data()
            if data and data.text:
                self.input.buffer.insert_text(data.text)

        @bindings.add("c-o")
        def _(event):
            if not self._tool_blocks:
                return
            last_idx = len(self._tool_blocks) - 1
            if last_idx in self._tool_expanded:
                self._tool_expanded.discard(last_idx)
                self.set_status("Tool output collapsed.")
            else:
                self._tool_expanded.add(last_idx)
                self.set_status("Tool output expanded. Ctrl+O to collapse.")
            self._rebuild_transcript()

        @bindings.add("c-q")
        @bindings.add("c-d")
        def _(event):
            if self._pending_input is not None and not self._pending_input.done():
                self._pending_input.set_exception(EOFError())

        return bindings

    def _get_theme_color(self) -> str:
        name = str(self.model_name).lower()
        if "openai" in name:
            return "#10b981"  # Emerald/Green
        elif "google" in name or "gemini" in name:
            return "#8b5cf6"  # Violet/Purple
        elif "anthropic" in name or "claude" in name:
            return "#f97316"  # Orange
        elif "ollama" in name or "llama" in name:
            return "#a855f7"  # Purple
        elif "mistral" in name:
            return "#ff8c00"  # Mistral dark orange
        else:
            return "#ffaa00"  # Default gold/orange

    def _get_prompt_text(self):
        theme_color = self._get_theme_color()
        return [("fg:" + theme_color + " bold", "❯ ")]

    def _get_status_bar_text(self):
        if isinstance(self._status, list):
            return self._status
        
        try:
            columns = self.app.output.get_size().columns
        except Exception:
            columns = 80

        spinner = ["|", "/", "-", "\\"][self._spinner_index % 4] if self._spinner_active else ""
        theme_color = self._get_theme_color()
        
        left_parts = []
        if self._spinner_active or self._status_display:
            if spinner:
                left_parts.append(("fg:" + theme_color + " bold", f"  {spinner}  "))
            else:
                left_parts.append(("fg:" + theme_color + " bold", "  ●  "))
            left_parts.append(("fg:" + theme_color, self._status_display))
        else:
            left_parts = [
                ("fg:#666666", "  "),
                ("fg:#888888 bold", "Ctrl+O"),
                ("fg:#555555", " Toggle Details  │  "),
                ("fg:#888888 bold", "Ctrl+Space"),
                ("fg:#555555", " Copy Mode  │  "),
                ("fg:#888888 bold", "Tab"),
                ("fg:#555555", " Switch Focus"),
            ]

        provider_map = {
            "openai": "OpenAI",
            "google": "Google Gemini",
            "anthropic": "Anthropic Claude",
            "ollama": "Ollama (Local)",
            "mistral": "Mistral AI"
        }
        raw_name = str(self.model_name).lower()
        display_model = provider_map.get(raw_name, self.model_name)

        mode_text = "Ask" if self.tool_approval_mode == "ask" else "Auto"
        mode_color = "#ffaa00" if self.tool_approval_mode == "ask" else "#10b981"
        plan_text = "ON" if self.plan_mode else "OFF"
        plan_color = "#00ffff" if self.plan_mode else "#666666"

        right_parts = [
            ("fg:#888888 bold", "Ctrl+T "),
            ("fg:" + mode_color, mode_text),
            ("fg:#555555", "  │  "),
            ("fg:#888888 bold", "Shift+Tab Plan "),
            ("fg:" + plan_color, plan_text),
            ("fg:#555555", "  │  "),
            ("fg:" + theme_color + " bold", display_model),
            ("fg:#666666", "  ")
        ]

        left_len = sum(len(text) for _, text in left_parts)
        right_len = sum(len(text) for _, text in right_parts)

        spaces_count = max(1, columns - left_len - right_len)
        spaces = " " * spaces_count

        return left_parts + [("", spaces)] + right_parts

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

    def _selection_block(self) -> str:
        if not self._selection_options:
            return ""
        lines = [self._selection_title]
        for index, option in enumerate(self._selection_options):
            prefix = ">" if index == self._selection_index else " "
            suffix = f"  [{option['thread_id'][:8]}]" if 'thread_id' in option else ""
            lines.append(f"{prefix} {index + 1}. {option['label']}{suffix}")
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
            elif chunk['type'] == 'thought':
                idx = chunk['idx']
                tb = self._thought_blocks[idx]
                text += self._thought_block_text(idx, tb['elapsed'], tb['tokens'], tb['content'], tb['in_flight'])
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
        self._thought_blocks.clear()
        self._auto_scroll = True
        self._rebuild_transcript()

    def start_bot_message(self):
        self._spinner_active = True
        if self._spinner_task is None or self._spinner_task.done():
            self._spinner_task = asyncio.create_task(self._run_spinner())
            
        self._chunks.append({'type': 'bot', 'text': '❯ '})
        self._rebuild_transcript()

    def update_bot_message(self, text: str):
        if not self._chunks or self._chunks[-1]['type'] != 'bot':
            self.start_bot_message()
        self._chunks[-1]['text'] = '❯ ' + format_ai_output(text)
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
        
        friendly = get_friendly_tool_name(tool_name)
        if friendly != tool_name:
            if first_line.startswith(tool_name + "("):
                first_line = friendly + first_line[len(tool_name):]
            elif first_line.startswith(tool_name + " "):
                first_line = friendly + first_line[len(tool_name):]
            elif first_line == tool_name:
                first_line = friendly
        
        header = f"{TOOL_HEADER_MARKER}● {first_line}"
        expanded = idx in self._tool_expanded

        def format_body(lines_list):
            if not lines_list:
                return f"{TOOL_BODY_MARKER}  (No output)"
            return "\n".join(f"{TOOL_BODY_MARKER}  {l}" for l in lines_list)

        if in_flight:
            braille_chars = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]
            spinner_char = braille_chars[self._spinner_index % len(braille_chars)]
            
            header = f"{TOOL_HEADER_MARKER}● {first_line} (ctrl+o to expand)"
            body = (
                f"{TOOL_BODY_MARKER}{spinner_char} Generating...\n"
                f"{TOOL_BODY_MARKER}└ Tip: Press ctrl+g to open an external editor for long prompts.\n"
                f"{TOOL_BODY_MARKER}───────────────────────────────────────────────────────────────────"
            )
            return f"\n{header}\n{body}\n"

        if not in_flight and not expanded:
            hint = f"{HINT_MARKER}  (ctrl+o to expand)"
            return f"\n{header}\n{hint}\n"
            
        if not in_flight and expanded:
            body_lines = lines[1:] if len(lines) > 1 else []
            body = format_body(body_lines)
            hint = f"{HINT_MARKER}  (ctrl+o to collapse)"
            return f"\n{header}\n{body}\n{hint}\n"

        return f"\n{header}\n{hint}\n"

    def start_thought(self) -> int:
        idx = len(self._thought_blocks)
        self._thought_blocks.append({
            'elapsed': 0.0,
            'tokens': 0,
            'content': "",
            'in_flight': True,
            'start_time': time.time()
        })
        self._chunks.append({'type': 'thought', 'idx': idx})
        self._rebuild_transcript()
        return idx

    def update_thought(self, idx: int, content: str, tokens: int = None, in_flight: bool = True):
        if 0 <= idx < len(self._thought_blocks):
            tb = self._thought_blocks[idx]
            tb['content'] = content
            tb['in_flight'] = in_flight
            tb['elapsed'] = time.time() - tb['start_time']
            if tokens is not None:
                tb['tokens'] = tokens
            else:
                tb['tokens'] = len(content.split())
            self._rebuild_transcript()

    def _thought_block_text(self, idx: int, elapsed: float, tokens: int, content: str, in_flight: bool) -> str:
        header = f"{THOUGHT_HEADER_MARKER}▸ Thought for {elapsed:.1f}s, {tokens} tokens"
        if not content.strip():
            return f"\n{header}\n"
        
        lines = content.rstrip().splitlines()
        body_lines = [f"{THOUGHT_BODY_MARKER}  {line}" for line in lines]
        body = "\n".join(body_lines)
        return f"\n{header}\n{body}\n"

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

    def set_status(self, text: str, show_spinner: bool = False):
        """Updates the status text, with an option to toggle the visual spinner."""
        self._status = text
        self._base_status = text
        if text:
            self._status_display = text
            if show_spinner and not self._spinner_active:
                self._spinner_active = True
                if self._spinner_task is None or self._spinner_task.done():
                    self._spinner_task = asyncio.create_task(self._run_spinner())
            elif not show_spinner:
                # If it's a static message, kill any active spinner task
                self._spinner_active = False
                if self._spinner_task is not None:
                    self._spinner_task.cancel()
                    self._spinner_task = None
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
        # Wrap the background worker in a supervisor to catch hidden async exceptions
        async def supervised_worker():
            try:
                await worker()
            except Exception as e:
                self.set_status("")
                # Forces prompt_toolkit to exit immediately and raise the error to run_async
                self.app.exit(exception=e)

        self.app.create_background_task(supervised_worker())
        
        try:
            await self.app.run_async()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            # This will now successfully catch background crashes!
            raise RuntimeError(f"ChatUI crashed unexpectedly: {e}") from e

    def get_clean_transcript_text(self) -> str:
        parts = []
        for chunk in self._chunks:
            if chunk['type'] == 'text':
                text = chunk['text']
                if text.startswith("> "):
                    text = "You: " + text[2:]
                parts.append((chunk['type'], text))
            elif chunk['type'] == 'bot':
                text = chunk['text']
                if text.startswith("❯ "):
                    text = "Saarthi: " + text[2:]
                parts.append((chunk['type'], text))
            elif chunk['type'] == 'time':
                parts.append((chunk['type'], chunk['text']))
            elif chunk['type'] == 'thought':
                idx = chunk['idx']
                tb = self._thought_blocks[idx]
                elapsed = tb['elapsed']
                tokens = tb['tokens']
                content = tb['content']
                thought_lines = [f"▸ Thought for {elapsed:.1f}s, {tokens} tokens"]
                for l in content.rstrip().splitlines():
                    thought_lines.append(f"  {l}")
                parts.append((chunk['type'], "\n".join(thought_lines)))
            elif chunk['type'] == 'tool':
                idx = chunk['idx']
                tb = self._tool_blocks[idx]
                full_output = tb['output']
                tool_name = tb['name']
                tool_lines = full_output.rstrip().splitlines()
                first_line = tool_lines[0] if tool_lines else tool_name
                tool_block_lines = [f"● {first_line}"]
                body_lines = tool_lines[1:] if len(tool_lines) > 1 else []
                for l in body_lines:
                    tool_block_lines.append(f"  {l}")
                parts.append((chunk['type'], "\n".join(tool_block_lines)))

        text_out = ""
        for i, (ctype, ctext) in enumerate(parts):
            if i > 0:
                prev_type = parts[i-1][0]
                if ctype in ('thought', 'tool') or prev_type in ('thought', 'tool', 'time'):
                    text_out += "\n\n"
                else:
                    text_out += "\n"
            text_out += ctext
            
        text_out = text_out.replace("\u200b", "")
        for marker in ("\u2001", "\u2002", "\u2003", "\u2004", "\u2005"):
            text_out = text_out.replace(marker, "")
        return text_out