import uuid
from typing import Literal

from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI, MistralAIEmbeddings
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.store.base import BaseStore
from pydantic import BaseModel, Field
import os

load_dotenv()

os.makedirs("data", exist_ok=True)

# ──────────────────────────────────────────
# Models
# ──────────────────────────────────────────

model = ChatMistralAI()
embedding_model = MistralAIEmbeddings()

# ──────────────────────────────────────────
# Prompts
# ──────────────────────────────────────────

SYSTEM_PROMPT_TEMPLATE = """You are a helpful assistant with memory capabilities.
If user-specific memory is available, use it to personalize
your responses based on what you know about the user.
Your goal is to provide relevant, friendly, and tailored
assistance that reflects the user's preferences, context, and past interactions.
If the user's name or relevant personal context is available, always personalize your responses by:
    - Address the user by name (e.g., "Sure, Snehangshu...") when appropriate
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
            "Get this key from the [key] prefix shown in existing memories. "
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
# Memory extractor
# ──────────────────────────────────────────

memory_extractor = model.with_structured_output(MemoryDecision)


# ──────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────

async def _list_all_memories(store: BaseStore, namespace: tuple) -> list:
    """
    Fetch every memory for this user without any score filter.
    list() returns all items; we fall back to a broad asearch if list() is unavailable.
    """
    try:
        # AsyncSqliteStore supports .alist() to retrieve all items in a namespace
        items = await store.alist(namespace)
    except AttributeError:
        # Fallback: search with a very generic query and no score cutoff
        items = await store.asearch(namespace, query="user profile preferences", limit=100)
    return list(items)


# ──────────────────────────────────────────
# Nodes
# ──────────────────────────────────────────

async def remember_node(state: ChatState, config: RunnableConfig, store: BaseStore):
    """Extract facts from the latest user message and persist them."""
    user_id = config["configurable"]["user_id"]
    namespace = ("user", user_id, "details")
    last_message = state["messages"][-1].content

    # FIX: fetch ALL existing memories (no score filter) so the extractor
    # has complete context and update/delete keys are always resolvable.
    all_items = await _list_all_memories(store, namespace)
    existing = (
        "\n".join(f"[{it.key}] {it.value.get('data', '')}" for it in all_items)
        if all_items
        else "(empty)"
    )

    decision: MemoryDecision = await memory_extractor.ainvoke([
        SystemMessage(content=MEMORY_PROMPT.format(user_details_content=existing)),
        {"role": "user", "content": last_message},
    ])

    if decision.should_write:
        # Build a key->item map from ALL items for reliable update/delete lookup
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
    """Retrieve ALL memories and call the model."""
    user_id = config["configurable"]["user_id"]
    namespace = ("user", user_id, "details")

    # FIX: load every memory, not just semantically similar ones.
    # Identity facts like name/username must always be visible regardless
    # of what the current message happens to be about.
    all_items = await _list_all_memories(store, namespace)
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
    messages.extend(state["messages"])

    response = await model.ainvoke(messages)
    return {"messages": [response]}


async def summarize_conversation(state: ChatState):
    """Summarise older messages to keep context window manageable."""
    existing_summary = state.get("summary", "")
    summary_prompt = (
        f"Existing summary:\n{existing_summary}\n\nExtend the summary using the new conversation above."
        if existing_summary
        else "Summarize the conversation above."
    )
    message_for_summary = state["messages"] + [HumanMessage(content=summary_prompt)]
    response = await model.ainvoke(message_for_summary)
    return {"summary": response.content}


# ──────────────────────────────────────────
# Conditional edge (must be sync)
# ──────────────────────────────────────────

def should_summarize(state: ChatState) -> str:
    return "summarize" if len(state["messages"]) % 6 == 0 else END


# ──────────────────────────────────────────
# Build graph
# ──────────────────────────────────────────

builder = StateGraph(ChatState)
builder.add_node("remember", remember_node)
builder.add_node("chat", chat_node)
builder.add_node("summarize", summarize_conversation)

builder.add_edge(START, "remember")
builder.add_edge("remember", "chat")
builder.add_conditional_edges(
    "chat",
    should_summarize,
    {"summarize": "summarize", END: END},
)
builder.add_edge("summarize", END)

uncompiled_builder = builder