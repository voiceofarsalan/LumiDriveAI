from typing import Dict, List

from langchain.memory import ConversationBufferMemory
from langchain.schema import AIMessage, HumanMessage, SystemMessage, BaseMessage


_MEMORIES: Dict[str, ConversationBufferMemory] = {}


def get_memory(session_id: str) -> ConversationBufferMemory:
    memory = _MEMORIES.get(session_id)
    if not memory:
        memory = ConversationBufferMemory(return_messages=True)
        _MEMORIES[session_id] = memory
    return memory


def bootstrap_memory_from_messages(memory: ConversationBufferMemory, messages: List[dict]):
    """
    Initialize a memory with existing chat history coming from the client.
    Only called when the memory is empty to avoid duplications.
    """
    if not messages:
        return
    if memory.chat_memory.messages:
        return
    for msg in messages:
        role = msg.get("role")
        content = msg.get("content", "")
        if not content:
            continue
        if role == "user":
            memory.chat_memory.add_user_message(content)
        elif role == "assistant":
            memory.chat_memory.add_ai_message(content)
        elif role == "system":
            memory.chat_memory.add_message(SystemMessage(content=content))


def memory_to_openai_messages(memory: ConversationBufferMemory, system_prompt: str) -> List[dict]:
    """
    Convert the LangChain memory contents into OpenAI chat-completion format.
    """
    out = [{"role": "system", "content": system_prompt}]
    for msg in memory.chat_memory.messages:
        role = None
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        elif isinstance(msg, SystemMessage):
            role = "system"
        elif isinstance(msg, BaseMessage):
            role = msg.type
        if role and msg.content:
            out.append({"role": role, "content": msg.content})
    return out

