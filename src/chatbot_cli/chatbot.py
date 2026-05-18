import uuid
from typing import Literal

from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage, BaseMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field

# ──────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant with memory capabilities.
If user-specific memory is available, use it to personalize
your responses based on what you know about the user.
Your goal is to provide relevant, friendly, and tailored
assistance that reflects the user's preferences, context, and past interactions.
If the user's name or relevant personal context is available, always personalize your responses by:
    - Address the user by name when appropriate
    - Reference known projects, tools, or preferences
    - Adjust the tone to feel friendly, natural, and directly aimed at the user
Avoid generic phrasing when personalization is possible.
Always ensure that personalization is based only on known user details and not assumed.
In the end suggest 3 relevant further questions based on the current response and user profile.
The user's memory (which may be empty) is provided as: {user_details_content}
"""

MEMORY_PROMPT = """You maintain accurate user memory.
Existing memories (format: [key] text):
{user_details_content}
From the user's latest message:
- Extract stable user-specific facts (identity, preferences, projects).
- For each fact decide the action:
    * add    -> completely new information not in existing memories
    * update -> replaces/corrects an existing memory (set replaces= to the EXACT KEY like abc-123)
    * delete -> existing memory is outdated (set replaces= to the EXACT KEY like abc-123)
- Set is_new=False for duplicates with no new info.
- Short atomic sentences only. No speculation.
- Nothing memory-worthy? Return should_write=false.
Example:
Existing: [abc-123] Prefers Python for programming
User says: "I switched to Java"
-> action=update, text="Prefers Java", replaces="abc-123"
"""

# ──────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────

class MemoryItem(BaseModel):
    text: str = Field(description="Atomic user memory")
    is_new: bool = Field(description="True if new, False if duplicate")
    action: Literal["add", "update", "delete"] = Field(
        description="add=new fact, update=replace existing, delete=remove outdated fact"
    )
    replaces: str = Field(
        default="",
        description=(
            "The EXACT KEY (e.g. 3f7a2b1c-9d4e-...) of the existing memory to update or delete. "
            "Empty string if action=add."
        ),
    )


class MemoryDecision(BaseModel):
    should_write: bool
    memories: list[MemoryItem] = Field(default_factory=list)


# ──────────────────────────────────────────
# State
# ──────────────────────────────────────────

class ChatState(MessagesState):
    summary: str


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

async def _get_all_memories(store: BaseStore, query: str, namespace: tuple) -> list:
    """asearch(query=None) returns all items — alist() does not exist."""
    return await store.asearch(namespace, query=query, limit=500)


def _sanitize_messages(messages: list[BaseMessage]) -> list[BaseMessage]:
    """
    Remove or fix messages that would cause a 400 from Mistral/OpenAI.
    Specifically:
    - AIMessage / AIMessageChunk with content=None or content=""
    These get stored in checkpoints from previous streaming sessions
    and cause 'Assistant message must have content' errors on replay.
    """
    clean = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            # skip assistant messages with empty/None content
            content = msg.content
            if not content:
                continue
            # if content is a list (tool use format), keep as-is
            if isinstance(content, list):
                clean.append(msg)
            else:
                clean.append(msg)
        else:
            clean.append(msg)
    return clean


def _latest_human_content(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return str(msg.content)
        if getattr(msg, "type", "") == "human":
            return str(getattr(msg, "content", ""))
        if isinstance(msg, dict) and msg.get("role") in {"human", "user"}:
            return str(msg.get("content", ""))
    return ""


# ──────────────────────────────────────────
# Build graph — called once from main.py
# ──────────────────────────────────────────

def build_graph(model, checkpointer, store, tools=None):
    """
    Compile and return the graph.
    Nodes are defined inside so they close over `model` naturally —
    no global registry needed.
    """
    tools = tools or []
    tool_map = {t.name: t for t in tools}
    model_with_tools = model.bind_tools(tools) if tools else model
    memory_extractor = model.with_structured_output(MemoryDecision)

    # ── nodes ──────────────────────────────

    async def remember_node(state: ChatState, config: RunnableConfig, store: BaseStore):
        """Extract facts from the latest user message and persist them."""
        user_id = config["configurable"]["user_id"]
        namespace = ("user", user_id, "details")
        last_message = _latest_human_content(state["messages"])
        if not last_message:
            return {}

        query = last_message + ". Are there any similar memories that should be updated or deleted?"
        all_items = await _get_all_memories(store, query, namespace)
        existing = (
            "\n".join(f"[{it.key}] {it.value.get('data', '')}" for it in all_items)
            if all_items else "(empty)"
        )

        decision: MemoryDecision = await memory_extractor.ainvoke([
            SystemMessage(content=MEMORY_PROMPT.format(user_details_content=existing)),
            {"role": "user", "content": last_message},
        ])

        if decision.should_write:
            item_map = {it.key: it for it in all_items}
            for mem in decision.memories:
                if not mem.is_new and mem.action == "add":
                    continue
                if mem.action == "add":
                    await store.aput(namespace, str(uuid.uuid4()), {"data": mem.text})
                elif mem.action == "update" and mem.replaces in item_map:
                    await store.aput(namespace, mem.replaces, {"data": mem.text})
                elif mem.action == "delete" and mem.replaces in item_map:
                    await store.adelete(namespace, mem.replaces)

        return {}

    async def chat_node(state: ChatState, config: RunnableConfig, store: BaseStore):
        """Retrieve all memories, sanitize history, stream response."""
        user_id = config["configurable"]["user_id"]
        namespace = ("user", user_id, "details")
        last_message = _latest_human_content(state["messages"])
        query = last_message + ". Are there any similar memories that should be updated or deleted?"
        all_items = await _get_all_memories(store, query, namespace)
        user_details = "\n".join(it.value["data"] for it in all_items) if all_items else ""

        messages = []

        if state.get("summary", ""):
            messages.append(
                SystemMessage(content=f"Conversation summary so far:\n{state['summary']}")
            )

        messages.append(
            SystemMessage(
                content=SYSTEM_PROMPT_TEMPLATE.format(
                    user_details_content=user_details or "(empty)"
                )
            )
        )

        # sanitize before sending — strips empty AIMessages from checkpointed history
        messages.extend(_sanitize_messages(state["messages"]))

        # invoke model (with tools bound if any)
        response = await model_with_tools.ainvoke(messages)

        # tool execution loop — keeps going until model stops calling tools
        while response.tool_calls:
            tool_messages = []
            for tc in response.tool_calls:
                t = tool_map.get(tc["name"])
                if t is None:
                    result = f"ERROR: unknown tool '{tc['name']}'"
                else:
                    try:
                        if hasattr(t, "ainvoke"):
                            result = await t.ainvoke(tc["args"])
                        else:
                            result = t.invoke(tc["args"])
                    except Exception as e:
                        result = f"ERROR: {e}"
                tool_messages.append(
                    ToolMessage(content=str(result), tool_call_id=tc["id"])
                )
            # append assistant tool-call message + results, then call model again
            messages = messages + [response] + tool_messages
            response = await model_with_tools.ainvoke(messages)

        final_message = AIMessage(content=response.content or "(no response)")
        return {"messages": [final_message]}

    async def summarize_conversation(state: ChatState):
        """Summarise older messages to keep context window manageable."""
        existing_summary = state.get("summary", "")
        summary_prompt = (
            f"Existing summary:\n{existing_summary}\n\nExtend the summary using the new conversation above."
            if existing_summary
            else "Summarize the conversation above."
        )
        # sanitize here too — summary node also reads full history
        clean_messages = _sanitize_messages(state["messages"])
        message_for_summary = clean_messages + [HumanMessage(content=summary_prompt)]
        response = await model.ainvoke(message_for_summary)
        return {"summary": response.content}

    # ── conditional edge ───────────────────

    def route_after_chat(state: ChatState) -> str:
        return "summarize" if len(state["messages"]) % 6 == 0 else "remember"

    # ── compile ────────────────────────────

    builder = StateGraph(ChatState)
    builder.add_node("remember", remember_node)
    builder.add_node("chat", chat_node)
    builder.add_node("summarize", summarize_conversation)

    builder.add_edge(START, "chat")
    builder.add_conditional_edges(
        "chat",
        route_after_chat,
        {"summarize": "summarize", "remember": "remember"},
    )
    builder.add_edge("summarize", "remember")
    builder.add_edge("remember", END)

    return builder.compile(checkpointer=checkpointer, store=store)