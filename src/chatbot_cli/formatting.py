from datetime import datetime
import re
from io import StringIO
from shutil import get_terminal_size
from rich.console import Console
from rich.markdown import Markdown

def message_content_text(message) -> str: # Extract text content from message
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


def message_role(message) -> str: # Extract role ("human", "ai", "assistant") from message
    if isinstance(message, dict):
        return str(message.get("role", ""))
    msg_type = getattr(message, "type", "")
    if msg_type:
        return str(msg_type)
    return type(message).__name__.replace("Message", "").lower()


def clip_text(text: str, limit: int = 90) -> str: # Truncate to 90 chars for session preview labels
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def format_checkpoint_time(ts: str) -> str: # ISO timestamp
    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


def render_messages(messages: list) -> str: # Render messages for display in transcript
    """
    Converts full message list → terminal transcript string.
    """
    blocks = []
    for message in messages:
        role = message_role(message)
        content = message_content_text(message)
        if not content:
            continue
        if role in {"human", "user"}:
            blocks.append(f"> {content}")
        elif role in {"ai", "assistant"}:
            blocks.append(format_ai_output(content))
    return "\n\n".join(blocks)


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from a string."""
    return _ANSI_ESCAPE.sub("", text)


def format_ai_output(text: str) -> str:

    # Render markdown to a string buffer using Rich, then strip the ANSI
    # escape codes that Rich injects.  prompt_toolkit's TextArea stores plain
    # text, so raw escape sequences would appear as literal ^[[1m garbage and
    # make text impossible to copy.
    buffer = StringIO()

    console = Console(
        file=buffer,
        force_terminal=False,   # plain text mode — no escape codes
        color_system=None,      # explicitly disable colour output
        width=max(40, get_terminal_size().columns - 6),
        highlight=False,
        markup=False,
    )

    console.print(Markdown(text))

    result = buffer.getvalue().rstrip()

    # Belt-and-suspenders: strip any residual ANSI codes in case Rich still
    # sneaks some through (e.g. from Markdown rule rendering).
    return strip_ansi(result)

def strip_code_fences(text: str) -> str:
    """Remove ```python, ``` lines. Keeps the actual code, drops the markdown wrapper."""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        if line.strip().startswith("```"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip("\n")


def looks_like_code(text: str) -> bool:
    code_patterns = (
        "def ",
        "class ",
        "import ",
        "from ",
        "return ",
        "{",
        "}",
        ";",
        "SELECT ",
        "#include",
    )

    text_lower = text.lower()

    return any(pattern.lower() in text_lower for pattern in code_patterns)