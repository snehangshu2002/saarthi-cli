from chatbot_cli.formatting import clip_text, format_checkpoint_time, message_content_text


def checkpoint_preview(checkpoint_tuple) -> str:
    channel_values = checkpoint_tuple.checkpoint.get("channel_values", {})
    summary = channel_values.get("summary")
    if isinstance(summary, str) and summary.strip():
        return clip_text(summary)

    messages = channel_values.get("messages", [])
    for message in reversed(messages):
        text = message_content_text(message)
        if text.startswith("Task exception was never retrieved"):
            continue
        if text:
            return clip_text(text)

    return "No saved preview"


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
                "label": f"{format_checkpoint_time(item.checkpoint.get('ts', ''))}  {checkpoint_preview(item)}",
            }
        )

    return sessions[:limit]


async def load_thread_snapshot(checkpointer, thread_id: str):
    config = {"configurable": {"thread_id": thread_id}}
    return await checkpointer.aget_tuple(config)
