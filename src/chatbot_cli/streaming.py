from langchain_core.messages import AIMessageChunk


async def stream_response(graph, user_input: str, config: dict, ui) -> str:
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
