"""Memory System - short-term conversation and long-term vector memory."""
import time
import uuid
from typing import List, Dict, Optional

from .knowledge_base import SimpleEmbedder, InMemoryVectorStore


class ConversationMemory:
    """Short-term memory: stores recent conversation messages."""

    def __init__(self, max_messages: int = 50):
        self.max_messages = max_messages
        self._store: Dict[str, List[Dict]] = {}

    def add(self, session_id: str, role: str, content: str):
        """Add a message to the conversation."""
        if session_id not in self._store:
            self._store[session_id] = []
        self._store[session_id].append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })
        if len(self._store[session_id]) > self.max_messages:
            self._store[session_id] = self._store[session_id][-self.max_messages:]

    def get(self, session_id: str, limit: Optional[int] = None) -> List[Dict]:
        """Get recent messages for a session."""
        messages = self._store.get(session_id, [])
        if limit:
            return messages[-limit:]
        return messages

    def clear(self, session_id: str):
        """Clear conversation history for a session."""
        self._store.pop(session_id, None)

    def summary(self, session_id: str) -> str:
        """Generate a simple summary of the conversation."""
        messages = self.get(session_id)
        if not messages:
            return "No conversation history."
        user_msgs = [m["content"] for m in messages if m["role"] == "user"]
        assistant_msgs = [m["content"] for m in messages if m["role"] == "assistant"]
        return (
            f"Conversation: {len(messages)} messages "
            f"({len(user_msgs)} user, {len(assistant_msgs)} assistant). "
            f"Recent: {messages[-1]['content'][:100]}"
        )


class LongTermMemory:
    """Long-term memory: stores facts and knowledge as vector embeddings."""

    def __init__(self):
        self.store = InMemoryVectorStore()
        self.embedder = SimpleEmbedder()

    def remember(self, session_id: str, content: str, metadata: Optional[Dict] = None):
        """Store a fact or piece of knowledge."""
        old_texts = [v["text"] for v in self.store.documents]
        all_texts = old_texts + [content]
        self.embedder.fit(all_texts)
        # Re-embed all existing documents with updated vocabulary
        new_vectors = self.embedder.embed_batch(all_texts)
        self.store.vectors = new_vectors[:-1]  # Update existing vectors
        new_vector = new_vectors[-1]  # Vector for the new content
        doc_id = f"mem_{session_id}_{uuid.uuid4().hex[:8]}"
        self.store.add(doc_id, content, metadata or {}, new_vector)

    def recall(self, query: str, top_k: int = 5) -> List[Dict]:
        """Retrieve relevant memories by semantic search."""
        query_vector = self.embedder.embed(query)
        return self.store.search(query_vector, top_k=top_k)

    def stats(self) -> Dict:
        """Get memory statistics."""
        return {
            "total_memories": len(self.store.documents),
            "vocab_size": len(self.embedder.vocab),
        }


class MemoryManager:
    """Unified memory management: conversation + long-term."""

    def __init__(self):
        self.conversation = ConversationMemory()
        self.long_term = LongTermMemory()

    def add_message(self, session_id: str, role: str, content: str):
        """Add a message to short-term memory."""
        self.conversation.add(session_id, role, content)

    def get_conversation(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Get recent conversation history."""
        return self.conversation.get(session_id, limit=limit)

    def remember(self, session_id: str, content: str):
        """Store knowledge in long-term memory."""
        self.long_term.remember(session_id, content)

    def recall(self, query: str, top_k: int = 5) -> List[Dict]:
        """Recall knowledge from long-term memory."""
        return self.long_term.recall(query, top_k)

    def clear_session(self, session_id: str):
        """Clear short-term memory for a session."""
        self.conversation.clear(session_id)

    def stats(self) -> Dict:
        return {
            "short_term_sessions": len(self.conversation._store),
            "long_term": self.long_term.stats(),
        }
