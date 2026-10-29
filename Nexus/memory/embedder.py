"""Embedder converts text to vector embeddings using all-MiniLM-L6-v2."""
from sentence_transformers import SentenceTransformer
from pathlib import Path
import numpy as np


class Embedder:
    """Converts text to vector embeddings for semantic search."""

    def __init__(self, model_name="all-MiniLM-L6-v2", cache_dir=None):
        self.model = SentenceTransformer(model_name, cache_folder=cache_dir)
        self.dimensions = self.model.get_sentence_embedding_dimension()

    def embed(self, text):
        """Generate embedding vector for a single text."""
        embedding = self.model.encode(text)
        return embedding.tolist()

    def embed_batch(self, texts):
        """Generate embeddings for a batch of texts."""
        embeddings = self.model.encode(texts)
        return embeddings.tolist()

    def similarity(self, vec_a, vec_b):
        """Compute cosine similarity between two vectors."""
        a = np.array(vec_a)
        b = np.array(vec_b)
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))