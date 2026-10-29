"""Memory module tests for Nexus."""

import pytest

from Nexus.memory.episodic import EpisodicMemory
from Nexus.memory.semantic import SemanticMemory
from Nexus.memory.embedder import Embedder


def test_episodic_memory(tmp_path):
    """Test EpisodicMemory basic operations."""
    memory = EpisodicMemory(tmp_path / "test_episodic.db")

    memory.add_event("clipboard", "copied some text")

    results = memory.search("copied")
    assert len(results) >= 1, "Should find the added event"

    timestamp, source, content = results[0]
    assert timestamp
    assert source == "clipboard"
    assert "copied some text" in content


def test_episodic_search_respects_limit(tmp_path):
    """Test that search only returns the requested number of events."""
    memory = EpisodicMemory(tmp_path / "limited.db")
    for i in range(5):
        memory.add_event("clipboard", f"copied item {i}")

    assert len(memory.search("copied", limit=2)) == 2


def test_episodic_round_trip_preserves_role(tmp_path):
    """Chat turns come back with the speaker role attached."""
    from Nexus.core.memory_manager import MemoryManager

    memory = MemoryManager(
        episodic_db_path=tmp_path / "role.db",
        semantic_persist_dir=tmp_path / "chroma",
    )
    memory.add_chat_message("user", "my favorite project is pineapple dashboard")
    memory.add_chat_message("assistant", "noted, that is your favorite project")

    user_hits = memory.query("pineapple dashboard")["episodic"]
    assistant_hits = memory.query("noted, that is")["episodic"]

    assert user_hits and user_hits[0]["role"] == "user"
    assert assistant_hits and assistant_hits[0]["role"] == "assistant"
    assert user_hits[0]["source"] == "chat"


def test_episodic_search_escapes_like_wildcards(tmp_path):
    """`%` and `_` in queries must match literally, not as wildcards."""
    memory = EpisodicMemory(tmp_path / "like.db")
    memory.add_event("chat", "progress: 100% of goals_done")
    memory.add_event("chat", "ordinary row without symbols")
    memory.add_event("chat", "decoy goalsXdone row")

    # Unescaped, '%' would match every row.
    percent_hits = memory.search("%")
    assert len(percent_hits) == 1
    assert "100%" in percent_hits[0][2]

    # Unescaped, '_' would make goals_done match the goalsXdone decoy.
    underscore_hits = memory.search("goals_done")
    assert len(underscore_hits) == 1
    assert "goals_done" in underscore_hits[0][2]


def test_semantic_memory(tmp_path):
    """Test SemanticMemory basic operations."""
    memory = SemanticMemory(tmp_path / "test_chroma")

    memory.add("This is a test document about python", "doc1")

    results = memory.query("python test", n_results=3)

    assert "documents" in results
    assert len(results["documents"]) > 0
    assert results["documents"][0]


def test_semantic_memory_batch(tmp_path):
    """Test batch insertion into semantic memory."""
    memory = SemanticMemory(tmp_path / "batch_chroma")

    memory.add_documents_batch(
        documents=["alpha document", "beta document"],
        ids=["a", "b"],
        metadatas=[{"source": "test"}, {"source": "test"}],
    )

    results = memory.query("alpha", n_results=2)
    assert results["documents"][0]


def test_embedder():
    """Test Embedder basic operations."""
    embedder = Embedder()

    vec = embedder.embed("hello world")
    assert isinstance(vec, list)
    assert len(vec) > 0
    assert all(isinstance(v, float) for v in vec)

    texts = ["hello world", "goodbye world"]
    vecs = embedder.embed_batch(texts)
    assert len(vecs) == 2
    assert all(isinstance(v, list) for v in vecs)

    vec_a = embedder.embed("hello world")
    vec_b = embedder.embed("hello world")
    vec_c = embedder.embed("goodbye world")

    same = embedder.similarity(vec_a, vec_b)
    diff = embedder.similarity(vec_a, vec_c)

    assert same > diff, "Identical texts should have higher similarity"
    assert same == pytest.approx(1.0, abs=1e-5)
    assert -1.0 <= diff <= 1.0


def test_embedder_dimensions():
    """Test that embedder reports correct dimensions."""
    embedder = Embedder()
    dim = embedder.dimensions
    assert dim > 0
    assert isinstance(dim, int)


def test_document_ingest_extension_handling(tmp_path):
    """`.doc` is rejected clearly, `.md` reads as text, `.d` is unsupported."""
    from Nexus.memory.document_ingest import DocumentIngestor

    ingestor = DocumentIngestor(embedder=object(), semantic_memory=None)

    legacy = tmp_path / "old.doc"
    legacy.write_text("legacy content")
    result = ingestor.ingest(str(legacy))
    assert result["success"] is False
    assert ".docx" in result["error"]

    stray = tmp_path / "notes.d"
    stray.write_text("stray extension that used to pass the substring check")
    result = ingestor.ingest(str(stray))
    assert result["success"] is False
    assert "Unsupported" in result["error"]

    md = tmp_path / "readme.md"
    md.write_text("# Title\n\nSome markdown body.")
    result = ingestor.ingest(str(md))
    assert result["success"] is True
    assert result["chunks_count"] >= 1


def test_document_ingest_content_hash_noop(tmp_path):
    """Unchanged content is a no-op; changed content replaces old chunks."""
    from Nexus.memory.document_ingest import DocumentIngestor

    class FakeStore:
        def __init__(self):
            self.rows = {}  # id -> filename
            self.deletes = 0

        def contains(self, doc_id):
            return f"{doc_id}_chunk_0" in self.rows

        def delete_where(self, where):
            self.deletes += 1
            name = where.get("filename")
            self.rows = {k: v for k, v in self.rows.items() if v != name}

        def add_documents_batch(self, documents, ids, metadatas):
            for row_id, meta in zip(ids, metadatas):
                self.rows[row_id] = meta["filename"]

    store = FakeStore()
    ingestor = DocumentIngestor(embedder=object(), semantic_memory=store)
    doc = tmp_path / "note.txt"
    doc.write_text("alpha beta gamma")

    first = ingestor.ingest(str(doc))
    assert first["success"] is True and not first.get("unchanged")
    assert store.deletes == 1

    second = ingestor.ingest(str(doc))
    assert second["success"] is True and second.get("unchanged") is True
    assert store.deletes == 1, "unchanged file must not re-ingest"
    assert second["doc_id"] == first["doc_id"]

    doc.write_text("alpha beta gamma CHANGED")
    third = ingestor.ingest(str(doc))
    assert third["success"] is True and not third.get("unchanged")
    assert store.deletes == 2, "old chunks must be purged before inserting"
    assert third["doc_id"] != first["doc_id"]


def test_chunk_text_terminates_when_overlap_exceeds_window():
    """A degenerate overlap must advance, never spin forever."""
    from Nexus.memory.document_ingest import DocumentIngestor

    ingestor = DocumentIngestor(embedder=object())
    ingestor.chunk_size = 20
    ingestor.chunk_overlap = 100  # larger than the window: the old loop's trap

    chunks = ingestor._chunk_text("x" * 500, "source")

    assert chunks, "chunks must be produced"
    assert 0 < len(chunks) <= 30, "loop must terminate and make progress"
