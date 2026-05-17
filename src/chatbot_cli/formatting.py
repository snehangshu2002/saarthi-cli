from datetime import datetime


def message_content_text(message) -> str:
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


def message_role(message) -> str:
    if isinstance(message, dict):
        return str(message.get("role", ""))
    msg_type = getattr(message, "type", "")
    if msg_type:
        return str(msg_type)
    return type(message).__name__.replace("Message", "").lower()


def clip_text(text: str, limit: int = 90) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def format_checkpoint_time(ts: str) -> str:
    try:
        return datetime.fromisoformat(ts).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


def render_messages(messages: list) -> str:
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


def format_ai_output(text: str) -> str:
    """Format assistant output for a plain terminal transcript."""
    text = strip_code_fences(text)
    if looks_like_code(text):
        return text
    lines = text.splitlines()
    if not lines:
        return "*"
    first = f"* {lines[0]}"
    rest = [f"  {line}" if line else "" for line in lines[1:]]
    return "\n".join([first, *rest])


def strip_code_fences(text: str) -> str:
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        if line.strip().startswith("```"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip("\n")


def looks_like_code(text: str) -> bool:
    if "\nclass " in f"\n{text}" or "\ndef " in f"\n{text}":
        return True
    code_markers = (
        "import ",
        "from ",
        "return ",
        "const ",
        "let ",
        "var ",
        "function ",
        "#include",
    )
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    return sum(line.startswith(code_markers) for line in lines) >= 2
