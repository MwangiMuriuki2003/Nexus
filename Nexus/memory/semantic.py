"""Semantic memory backed by ChromaDB."""
import chromadb
from pathlib import Path
from typing import List

from Nexus.memory.embedder import Embedder


class SemanticMemory:
    """Vector store for documents.

    Embeddings are computed with `Embedder` (the same all-MiniLM-L6-v2 model used
    elsewhere) and passed to ChromaDB explicitly, which keeps the store offline and
    avoids ChromaDB downloading its own copy of the model.
    """

    def __init__(self, persist_dir: Path, embedder: Embedder | None = None):
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.collection = self.client.get_or_create_collection(name="nexus_memory")
        self.embedder = embedder or Embedder()

    def add(self, text: str, doc_id: str, metadata: dict | None = None):
        kwargs = {
            "documents": [text],
            "ids": [doc_id],
            "embeddings": self.embedder.embed_batch([text]),
        }
        if metadata:
            kwargs["metadatas"] = [metadata]
        self.collection.add(**kwargs)

    def add_documents_batch(self, documents: List[str], ids: List[str], metadatas: List[dict | None] = None):
        """Add multiple documents to semantic memory in a batch.

        Args:
            documents: List of document text strings
            ids: List of unique document IDs (must match length of documents)
            metadatas: Optional list of metadata dicts (must match length of documents)
        """
        if metadatas is None:
            metadatas = [{} for _ in documents]

        assert len(documents) == len(ids) == len(metadatas), \
            "documents, ids, and metadatas must have the same length"

        kwargs = {
            "documents": documents,
            "ids": ids,
            "embeddings": self.embedder.embed_batch(documents),
        }
        # ChromaDB rejects empty metadata dicts, so only send them when populated.
        if any(metadatas):
            kwargs["metadatas"] = metadatas
        self.collection.add(**kwargs)

    def query(self, text: str, n_results: int = 5):
        return self.collection.query(
            query_embeddings=[self.embedder.embed(text)],
            n_results=n_results,
        )

    def count(self) -> int:
        return self.collection.count()

    def contains(self, doc_id: str) -> bool:
        """True when the first chunk of `doc_id` is already stored."""
        result = self.collection.get(ids=[f"{doc_id}_chunk_0"])
        return bool(result and result.get("ids"))

    def delete_where(self, where: dict) -> None:
        """Delete all chunks whose metadata matches `where` (e.g. {"filename": ...})."""
        self.collection.delete(where=where)
