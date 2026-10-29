"""Memory Manager coordinates episodic and semantic memory retrieval."""

from pathlib import Path

from Nexus.core.router import Intent, IntentRouter
from Nexus.memory.episodic import EpisodicMemory
from Nexus.memory.semantic import SemanticMemory


class MemoryManager:
    """Coordinates retrieval from both episodic and semantic memory stores."""

    def __init__(self, episodic_db_path: str | Path, semantic_persist_dir: str | Path):
        self.episodic = EpisodicMemory(Path(episodic_db_path))
        self.semantic = SemanticMemory(Path(semantic_persist_dir))
        self.router = IntentRouter()

    def query(self, message: str, top_k: int = 5, recent_limit: int = 10) -> dict:
        """Query both memory systems and combine results.

        Returns dict with 'episodic' and 'semantic' keys containing
        retrieved results formatted for LLM context.
        """
        # Parse intent to determine query strategy
        intent = self.router.route(message)

        results = {
            "episodic": [],
            "semantic": [],
            "intent": intent,
        }

        if intent == Intent.MEMORY_QUERY or intent == Intent.CHAT:
            # Episodic search: keyword match against timeline
            episodic_hits = self.episodic.search(message, limit=recent_limit, include_role=True)
            results["episodic"] = [
                {
                    "timestamp": row[0],
                    "source": row[1],
                    "content": row[2],
                    "role": row[3],
                }
                for row in episodic_hits
            ]

        if intent in (Intent.MEMORY_QUERY, Intent.CHAT, Intent.SKILL_CREATION):
            # Semantic search: vector similarity against embeddings
            semantic_hits = self.semantic.query(message, n_results=top_k)
            results["semantic"] = semantic_hits.get("documents", []) or []

        return results

    def add_chat_message(self, role: str, content: str, source: str = "chat"):
        """Store a chat message in episodic memory, preserving the speaker role."""
        self.episodic.add_event(source=source, content=content, role=role)

    def add_document(self, text: str, doc_id: str, metadata: dict | None = None):
        """Add a document to semantic memory."""
        self.semantic.add(text=text, doc_id=doc_id, metadata=metadata)