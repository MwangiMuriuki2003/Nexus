"""Document ingestion pipeline for Nexus.

Converts uploaded documents (PDF, DOCX, TXT) into vector embeddings
and stores them in semantic memory for later retrieval.

Supports:
- PDF files (via PyMuPDF/fitz)
- Microsoft Word documents (via python-docx)
- Plain text files
- Chunking for long documents
"""

import io
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional

from sentence_transformers import SentenceTransformer

from Nexus.memory.embedder import Embedder
from Nexus.memory.semantic import SemanticMemory


class DocumentChunk:
    """Represents a chunk of document text with metadata."""
    
    def __init__(self, text: str, source: str, chunk_index: int, 
                 metadata: Optional[Dict[str, Any]] = None):
        self.text = text
        self.source = source  # filename or path
        self.chunk_index = chunk_index
        self.metadata = metadata or {}


class DocumentIngestor:
    """Handles document upload, text extraction, and semantic indexing."""
    
    def __init__(self, embedder: Optional[Embedder] = None, 
                 semantic_memory: Optional[SemanticMemory] = None):
        self.embedder = embedder or Embedder()
        self.semantic_memory = semantic_memory
        self.chunk_size = 512  # tokens approximately
        self.chunk_overlap = 50
    
    def set_semantic_memory(self, memory: SemanticMemory):
        """Set the semantic memory store."""
        self.semantic_memory = memory
    
    def ingest(self, file_path: str) -> Dict[str, Any]:
        """Ingest a single document file.
        
        Args:
            file_path: Path to the document file
            
        Returns:
            Dict with ingestion results (chunks_count, doc_id, etc.)
        """
        file_path = Path(file_path)
        if not file_path.exists():
            return {"success": False, "error": f"File not found: {file_path}"}
        
        # Extract text based on extension
        ext = file_path.suffix.lower()
        text = ""
        
        try:
            if ext == ".pdf":
                text = self._extract_pdf(file_path)
            elif ext == ".docx":
                text = self._extract_docx(file_path)
            elif ext == ".doc":
                return {
                    "success": False,
                    "error": (
                        "Legacy .doc files are not supported; "
                        "convert the file to .docx first"
                    ),
                }
            elif ext in (".txt", ".md"):
                # Markdown is plain text as far as chunking/embedding goes.
                text = self._extract_txt(file_path)
            else:
                return {"success": False, "error": f"Unsupported file type: {ext}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to extract text: {e}"}
        
        if not text.strip():
            return {"success": False, "error": "No text extracted from document"}
        
        # Generate chunks
        chunks = self._chunk_text(text, str(file_path))
        
        # Content hash (not mtime): re-ingesting an unchanged file is a no-op,
        # and a changed file replaces its old chunks instead of piling up.
        doc_id = f"doc_{file_path.stem}_{self._content_hash(text)}"
        
        if self.semantic_memory:
            try:
                if self.semantic_memory.contains(doc_id):
                    return {
                        "success": True,
                        "doc_id": doc_id,
                        "filename": file_path.name,
                        "chunks_count": 0,
                        "unchanged": True,
                        "method": "semantic_memory",
                    }
                # Changed file: drop the previous chunks for this filename.
                self.semantic_memory.delete_where({"filename": file_path.name})
                # Add in batches to avoid ChromaDB limits
                for i in range(0, len(chunks), 10):
                    batch = chunks[i:i+10]
                    docs = [chunk.text for chunk in batch]
                    ids = [f"{doc_id}_chunk_{chunk.chunk_index}" for chunk in batch]
                    metadatas = [
                        {
                            "source": chunk.source,
                            "chunk_index": chunk.chunk_index,
                            "filename": file_path.name,
                        }
                        for chunk in batch
                    ]
                    self.semantic_memory.add_documents_batch(
                        documents=docs,
                        ids=ids,
                        metadatas=metadatas,
                    )
                return {
                    "success": True,
                    "doc_id": doc_id,
                    "filename": file_path.name,
                    "chunks_count": len(chunks),
                    "method": "semantic_memory",
                }
            except Exception as e:
                return {"success": False, "error": f"Failed to add to semantic memory: {e}"}
        else:
            return {
                "success": True,
                "doc_id": doc_id,
                "filename": file_path.name,
                "chunks_count": len(chunks),
                "method": "chunks_generated_but_no_memory_store",
            }
    
    @staticmethod
    def _content_hash(text: str) -> str:
        """Stable identity for extracted text (independent of mtime)."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def _extract_pdf(self, file_path: Path) -> str:
        """Extract text from PDF using PyMuPDF."""
        import fitz  # PyMuPDF
        text = ""
        with fitz.open(file_path) as doc:
            for page_num in range(len(doc)):
                page = doc[page_num]
                text += page.get_text()
        return text
    
    def _extract_docx(self, file_path: Path) -> str:
        """Extract text from DOCX using python-docx."""
        from docx import Document
        doc = Document(file_path)
        text = ""
        for para in doc.paragraphs:
            text += para.text + "\n"
        return text
    
    def _extract_txt(self, file_path: Path) -> str:
        """Extract text from TXT file."""
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    
    def _chunk_text(self, text: str, source: str) -> List[DocumentChunk]:
        """Split text into overlapping chunks for better retrieval."""
        if len(text) <= self.chunk_size:
            return [DocumentChunk(text=text, source=source, chunk_index=0)]
        
        chunks = []
        start = 0
        chunk_index = 0
        
        while start < len(text):
            end = start + self.chunk_size
            chunk_text = text[start:end]
            
            # Try to break at a sentence boundary
            if end < len(text):
                last_period = chunk_text.rfind(".")
                if last_period > self.chunk_size // 2:
                    end = start + last_period + 1
                    chunk_text = text[start:end]
            
            # Never let a degenerate boundary collapse the window: that would
            # stall `start` and spin forever.
            if end <= start:
                end = start + self.chunk_size
                chunk_text = text[start:end]
            
            chunks.append(DocumentChunk(
                text=chunk_text.strip(),
                source=source,
                chunk_index=chunk_index,
            ))
            
            next_start = end - self.chunk_overlap
            if next_start <= start:
                # Overlap >= window: advance by one chunk instead of looping.
                next_start = end
            start = next_start
            chunk_index += 1
            
            if start >= len(text):
                break
        
        return chunks


# Convenience function for quick ingestion
def ingest_document(file_path: str, embedder=None, semantic_memory=None) -> Dict[str, Any]:
    """Quickly ingest a document.
    
    Args:
        file_path: Path to document
        embedder: Optional Embedder instance
        semantic_memory: Optional SemanticMemory instance
        
    Returns:
        Ingestion result dict
    """
    ingestor = DocumentIngestor(embedder=embedder, semantic_memory=semantic_memory)
    return ingestor.ingest(file_path)


# Auto-discover supported extensions
SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}


def is_supported_file(file_path: str) -> bool:
    """Check if a file type is supported for ingestion."""
    return Path(file_path).suffix.lower() in SUPPORTED_EXTENSIONS


def get_supported_extensions() -> List[str]:
    """Get list of supported file extensions."""
    return list(SUPPORTED_EXTENSIONS)