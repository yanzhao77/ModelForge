"""RAG Knowledge Base - document ingestion and retrieval.

Supports: PDF, Markdown, TXT, Code files.
Flow: File -> Chunk -> Embedding -> VectorStore -> Retriever -> LLM.
"""
import os
import re
import hashlib
from pathlib import Path
from typing import List, Dict, Optional, Tuple

import numpy as np


class SimpleEmbedder:
    """Lightweight embedding using TF-IDF-like bag-of-words vectors.

    For production, replace with sentence-transformers or BGE embeddings.
    """

    def __init__(self):
        self.vocab: Dict[str, int] = {}

    def fit(self, texts: List[str]):
        """Build vocabulary from texts."""
        for text in texts:
            for token in self._tokenize(text):
                if token not in self.vocab:
                    self.vocab[token] = len(self.vocab)

    def embed(self, text: str) -> np.ndarray:
        """Convert text to a sparse vector using the fitted vocabulary."""
        vec = np.zeros(len(self.vocab) or 1, dtype=np.float32)
        tokens = self._tokenize(text)
        for token in tokens:
            idx = self.vocab.get(token)
            if idx is not None:
                vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec

    def embed_batch(self, texts: List[str]) -> List[np.ndarray]:
        return [self.embed(t) for t in texts]

    def _tokenize(self, text: str) -> List[str]:
        """Simple word-level tokenization."""
        return re.findall(r"[\w]+", text.lower())


class InMemoryVectorStore:
    """In-memory vector store with cosine similarity search."""

    def __init__(self):
        self.documents: List[Dict] = []
        self.vectors: List[np.ndarray] = []

    def add(self, doc_id: str, text: str, metadata: Dict, vector: np.ndarray):
        self.documents.append({"id": doc_id, "text": text, "metadata": metadata})
        self.vectors.append(vector)

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> List[Dict]:
        """Search for top-k similar documents."""
        if not self.vectors:
            return []
        scores = np.array([np.dot(query_vector, v) for v in self.vectors])
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            if scores[idx] > 0:
                doc = self.documents[idx].copy()
                doc["score"] = float(scores[idx])
                results.append(doc)
        return results


class TextChunker:
    """Splits text into overlapping chunks."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, text: str) -> List[str]:
        """Split text into chunks by paragraphs then by size."""
        paragraphs = text.split("\n\n")
        chunks = []
        current = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if len(current) + len(para) <= self.chunk_size:
                current += ("\n\n" + para) if current else para
            else:
                if current:
                    chunks.append(current)
                current = para
                while len(current) > self.chunk_size:
                    split_point = current[:self.chunk_size].rfind(" ")
                    if split_point == -1:
                        split_point = self.chunk_size
                    chunks.append(current[:split_point])
                    current = current[max(0, split_point - self.chunk_overlap):]

        if current:
            chunks.append(current)

        return chunks


class FileParser:
    """Parse various file types into plain text."""

    SUPPORTED_EXTENSIONS = {
        ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".java",
        ".go", ".rs", ".cpp", ".c", ".h", ".html", ".css", ".json",
        ".yaml", ".yml", ".xml", ".toml", ".cfg", ".ini",
    }

    def parse(self, filepath: str) -> Tuple[str, Dict]:
        """Parse a file and return (text_content, metadata)."""
        path = Path(filepath)
        ext = path.suffix.lower()

        if ext == ".pdf":
            return self._parse_pdf(path)
        elif ext in self.SUPPORTED_EXTENSIONS:
            return self._parse_text(path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    def _parse_text(self, path: Path) -> Tuple[str, Dict]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content, {"filename": path.name, "type": "text", "size": path.stat().st_size}

    def _parse_pdf(self, path: Path) -> Tuple[str, Dict]:
        """Parse PDF using PyPDF2 or pdfplumber if available."""
        try:
            import PyPDF2
            text = ""
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() or ""
            return text.strip(), {"filename": path.name, "type": "pdf", "pages": len(reader.pages)}
        except ImportError:
            pass
        try:
            import pdfplumber
            text = ""
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    text += page.extract_text() or ""
            return text.strip(), {"filename": path.name, "type": "pdf"}
        except ImportError:
            raise RuntimeError(
                "PDF parsing requires PyPDF2 or pdfplumber. "
                "Install with: pip install PyPDF2"
            )


class KnowledgeBase:
    """RAG Knowledge Base: ingest documents and query them."""

    def __init__(self):
        self.vector_store = InMemoryVectorStore()
        self.embedder = SimpleEmbedder()
        self.chunker = TextChunker()
        self.parser = FileParser()
        self._docs_count = 0

    def upload(self, filepath: str) -> Dict:
        """Ingest a file: parse, chunk, embed, and index."""
        text, metadata = self.parser.parse(filepath)
        if not text.strip():
            return {"status": "empty", "file": filepath, "chunks": 0}

        chunks = self.chunker.split(text)
        self.embedder.fit(chunks)

        vectors = self.embedder.embed_batch(chunks)

        file_id = hashlib.md5(filepath.encode()).hexdigest()[:12]
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            doc_id = f"{file_id}_{i}"
            chunk_meta = {**metadata, "chunk_index": i, "total_chunks": len(chunks)}
            self.vector_store.add(doc_id, chunk, chunk_meta, vector)

        self._docs_count += 1
        return {
            "status": "ingested",
            "file": filepath,
            "chunks": len(chunks),
            "type": metadata.get("type", "unknown"),
        }

    def query(self, question: str, top_k: int = 5) -> Dict:
        """Query the knowledge base and return relevant chunks."""
        query_vector = self.embedder.embed(question)
        results = self.vector_store.search(query_vector, top_k=top_k)

        return {
            "question": question,
            "results": [
                {
                    "text": r["text"][:300],
                    "score": round(r["score"], 4),
                    "source": r["metadata"].get("filename", ""),
                }
                for r in results
            ],
            "total_results": len(results),
        }

    def stats(self) -> Dict:
        """Return knowledge base statistics."""
        return {
            "documents": self._docs_count,
            "chunks": len(self.vector_store.documents),
            "vocab_size": len(self.embedder.vocab),
        }
