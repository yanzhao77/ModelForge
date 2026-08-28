"""RAG Knowledge Base - document ingestion, persistent storage, and retrieval.

Supports: PDF, Markdown, TXT, Code files.
Flow: File -> Chunk -> Embedding -> VectorStore -> Retriever -> LLM.

Persistence: when a SQLAlchemy session is passed (db != None), documents and
chunks are stored in knowledge_documents/knowledge_chunks and the in-memory
index is rebuilt from the DB on first use. Without db, behaves as before
(pure in-memory) so unit tests keep working.
"""
import hashlib
import json
import re
from pathlib import Path

import numpy as np
from models.records import (
    KnowledgeChunk,
    KnowledgeCollection,
    KnowledgeCollectionDocument,
    KnowledgeDocument,
)


class SimpleEmbedder:
    """Lightweight embedding using TF-IDF-like bag-of-words vectors."""

    def __init__(self):
        self.vocab: dict[str, int] = {}

    def fit(self, texts: list[str]):
        for text in texts:
            for token in self._tokenize(text):
                if token not in self.vocab:
                    self.vocab[token] = len(self.vocab)

    def embed(self, text: str) -> np.ndarray:
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

    def embed_batch(self, texts: list[str]) -> list[np.ndarray]:
        return [self.embed(t) for t in texts]

    def _tokenize(self, text: str) -> list[str]:
        return re.findall(r"[\w]+", text.lower())


class InMemoryVectorStore:
    """In-memory vector store with cosine similarity search."""

    def __init__(self):
        self.documents: list[dict] = []
        self.vectors: list[np.ndarray] = []

    def add(self, doc_id: str, text: str, metadata: dict, vector: np.ndarray):
        self.documents.append({"id": doc_id, "text": text, "metadata": metadata})
        self.vectors.append(vector)

    def search(self, query_vector: np.ndarray, top_k: int = 5) -> list[dict]:
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

    def clear(self):
        self.documents = []
        self.vectors = []

    def remove_by_metadata(self, key: str, value):
        keep = [
            (d, v) for d, v in zip(self.documents, self.vectors, strict=False)
            if d["metadata"].get(key) != value
        ]
        self.documents = [d for d, _ in keep]
        self.vectors = [v for _, v in keep]


class TextChunker:
    """Splits text into overlapping chunks."""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def split(self, text: str) -> list[str]:
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

    def parse(self, filepath: str) -> tuple[str, dict]:
        path = Path(filepath)
        ext = path.suffix.lower()
        if ext == ".pdf":
            return self._parse_pdf(path)
        elif ext in self.SUPPORTED_EXTENSIONS:
            return self._parse_text(path)
        else:
            raise ValueError(f"Unsupported file type: {ext}")

    def _parse_text(self, path: Path) -> tuple[str, dict]:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        return content, {"filename": path.name, "type": "text", "size": path.stat().st_size}

    def _parse_pdf(self, path: Path) -> tuple[str, dict]:
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
                "PDF parsing requires PyPDF2 or pdfplumber. Install with: pip install PyPDF2"
            )


class KnowledgeBase:
    """RAG Knowledge Base: ingest documents and query them (optionally persistent)."""

    def __init__(self):
        self.vector_store = InMemoryVectorStore()
        self.embedder = SimpleEmbedder()
        self.chunker = TextChunker()
        self.parser = FileParser()
        self._docs_count = 0
        self._db_loaded = False

    def _ensure_loaded(self, db=None):
        """Rebuild the in-memory index from the DB once (lazy)."""
        if db is None or self._db_loaded:
            return
        try:
            for _doc in db.query(KnowledgeDocument).all():
                self._docs_count += 1
            chunks = (
                db.query(KnowledgeChunk)
                .order_by(KnowledgeChunk.doc_id, KnowledgeChunk.chunk_index)
                .all()
            )
            for ch in chunks:
                meta = json.loads(ch.meta) if ch.meta else {}
                self.vector_store.add(
                    f"db_{ch.doc_id}_{ch.chunk_index}", ch.content, meta, None
                )
            texts = [d["text"] for d in self.vector_store.documents]
            self.embedder.fit(texts)
            self.vector_store.vectors = self.embedder.embed_batch(texts)
            self._db_loaded = True
        except Exception:
            # DB not ready (e.g. table missing) -> in-memory only
            self._db_loaded = True

    def upload(self, filepath: str, db=None, user_id: int | None = None, filename: str | None = None) -> dict:
        """Ingest a file: parse, chunk, embed, index (and persist when db given)."""
        text, metadata = self.parser.parse(filepath)
        if filename:
            metadata["filename"] = filename
        if not text.strip():
            return {"status": "empty", "file": filepath, "chunks": 0}

        chunks = self.chunker.split(text)
        self._ensure_loaded(db)
        all_texts = [d["text"] for d in self.vector_store.documents] + chunks
        self.embedder.fit(all_texts)
        new_vectors = self.embedder.embed_batch(all_texts)
        old_count = len(self.vector_store.documents)
        self.vector_store.vectors = new_vectors[:old_count]
        new_vecs = new_vectors[old_count:]

        file_id = hashlib.md5(filepath.encode()).hexdigest()[:12]
        chunk_meta_base = {"filename": metadata.get("filename", Path(filepath).name), "type": metadata.get("type", "text")}
        for i, (chunk, vector) in enumerate(zip(chunks, new_vecs, strict=False)):
            doc_id = f"{file_id}_{i}"
            chunk_meta = {**chunk_meta_base, "chunk_index": i, "total_chunks": len(chunks)}
            self.vector_store.add(doc_id, chunk, chunk_meta, vector)
        self._docs_count += 1

        if db is not None and user_id is not None:
            doc = KnowledgeDocument(
                user_id=user_id,
                filename=metadata.get("filename", filename or Path(filepath).name),
                filetype=metadata.get("type", "text"),
                chunk_count=len(chunks),
                doc_meta=json.dumps(metadata, ensure_ascii=False),
            )
            db.add(doc)
            db.flush()
            for i, chunk in enumerate(chunks):
                db.add(
                    KnowledgeChunk(
                        doc_id=doc.id,
                        chunk_index=i,
                        content=chunk,
                        meta=json.dumps({**chunk_meta_base, "chunk_index": i, "total_chunks": len(chunks)}, ensure_ascii=False),
                    )
                )
            db.commit()

        return {
            "status": "ingested",
            "file": filepath,
            "chunks": len(chunks),
            "type": metadata.get("type", "unknown"),
        }

    @staticmethod
    def normalize_binding(binding: dict | None = None) -> dict:
        """Normalize an explicit knowledge range without broadening access."""
        raw = dict(binding or {})
        collection_ids = list(dict.fromkeys(str(item) for item in raw.get("collection_ids") or raw.get("collections") or [] if item))
        mode = str(raw.get("mode") or ("collections" if collection_ids else "all"))
        if mode not in {"all", "collections", "disabled"}:
            raise ValueError("knowledge binding mode must be all, collections, or disabled")
        if mode == "collections" and not collection_ids:
            raise ValueError("collections knowledge binding requires collection_ids")
        return {"mode": mode, "collection_ids": collection_ids}

    def query(self, question: str, top_k: int = 5, db=None, user_id: int | None = None, knowledge_binding: dict | None = None) -> dict:
        self._ensure_loaded(db)
        binding = self.normalize_binding(knowledge_binding)
        if binding["mode"] == "disabled":
            return {"question": question, "results": [], "total_results": 0, "knowledge_binding": binding}
        query_vector = self.embedder.embed(question)
        if db is not None and user_id is not None:
            query = (
                db.query(KnowledgeChunk)
                .join(KnowledgeDocument, KnowledgeChunk.doc_id == KnowledgeDocument.id)
                .filter(KnowledgeDocument.user_id == user_id)
            )
            if binding["mode"] == "collections":
                query = (
                    query.join(KnowledgeCollectionDocument, KnowledgeCollectionDocument.document_id == KnowledgeDocument.id)
                    .join(KnowledgeCollection, KnowledgeCollection.id == KnowledgeCollectionDocument.collection_id)
                    .filter(KnowledgeCollection.user_id == user_id, KnowledgeCollection.id.in_(binding["collection_ids"]))
                )
            rows = query.distinct().all()
            collection_names: dict[int, list[dict]] = {}
            if rows:
                doc_ids = {row.doc_id for row in rows}
                memberships = (
                    db.query(KnowledgeCollectionDocument.document_id, KnowledgeCollection.id, KnowledgeCollection.name)
                    .join(KnowledgeCollection, KnowledgeCollection.id == KnowledgeCollectionDocument.collection_id)
                    .filter(KnowledgeCollectionDocument.document_id.in_(doc_ids), KnowledgeCollection.user_id == user_id)
                    .all()
                )
                for document_id, collection_id, name in memberships:
                    collection_names.setdefault(document_id, []).append({"id": collection_id, "name": name})
            vectors = self.embedder.embed_batch([row.content for row in rows]) if rows else []
            ranked = sorted(
                zip(rows, vectors, strict=False),
                key=lambda pair: float(np.dot(query_vector, pair[1])),
                reverse=True,
            )[:top_k]
            results = [
                {
                    "text": row.content,
                    "score": float(np.dot(query_vector, vector)),
                    "metadata": json.loads(row.meta) if row.meta else {},
                    "document_id": row.doc_id,
                    "chunk_id": row.id,
                    "collections": collection_names.get(row.doc_id, []),
                }
                for row, vector in ranked
                if float(np.dot(query_vector, vector)) > 0
            ]
        else:
            results = self.vector_store.search(query_vector, top_k=top_k)
        return {
            "question": question,
            "results": [
                {
                    "text": item["text"][:300],
                    "score": round(item["score"], 4),
                    "source": item["metadata"].get("filename", ""),
                    "chunk_index": item["metadata"].get("chunk_index"),
                    "document_id": item.get("document_id"),
                    "chunk_id": item.get("chunk_id"),
                    "collections": item.get("collections", []),
                }
                for item in results
            ],
            "total_results": len(results),
            "knowledge_binding": binding,
        }

    async def answer(
        self, question: str, top_k: int = 5, db=None, user_id: int | None = None, runtime=None, model: str = "default-model", knowledge_binding: dict | None = None
    ) -> dict:
        """RAG answer: retrieve relevant chunks, then generate with the runtime."""
        query_result = self.query(question, top_k=top_k, db=db, user_id=user_id, knowledge_binding=knowledge_binding)
        sources = query_result["results"]
        if not sources:
            return {"answer": "知识库中没有找到相关内容。", "sources": []}
        context = "\n\n".join(f"[{s['source']}] {s['text']}" for s in sources)
        prompt = f"[知识库内容]\n{context}\n\n问题: {question}\n请基于以上知识库内容回答。"
        if runtime is None:
            return {
                "answer": "未配置运行时，无法生成回答。检索结果如下：\n" + context,
                "sources": sources,
            }
        result = await runtime.chat(model, [{"role": "user", "content": prompt}])
        return {"answer": result.get("content", ""), "sources": sources}

    def documents(self, db=None, user_id: int | None = None) -> list[dict]:
        if db is not None:
            query = db.query(KnowledgeDocument)
            if user_id is not None:
                query = query.filter(KnowledgeDocument.user_id == user_id)
            docs = query.order_by(KnowledgeDocument.created_at.desc()).all()
            return [d.to_dict() for d in docs]
        seen = {}
        for doc in self.vector_store.documents:
            name = doc["metadata"].get("filename", "?")
            seen.setdefault(name, {"filename": name, "chunks": 0})
            seen[name]["chunks"] += 1
        return list(seen.values())

    def delete_document(self, filename: str, db=None, user_id: int | None = None) -> bool:
        if db is not None:
            query = db.query(KnowledgeDocument).filter(KnowledgeDocument.filename == filename)
            if user_id is not None:
                query = query.filter(KnowledgeDocument.user_id == user_id)
            doc = query.first()
            if doc is None:
                return False
            db.query(KnowledgeChunk).filter(KnowledgeChunk.doc_id == doc.id).delete()
            db.delete(doc)
            db.commit()
        before = len(self.vector_store.documents)
        self.vector_store.remove_by_metadata("filename", filename)
        if before > len(self.vector_store.documents):
            self._docs_count = max(0, self._docs_count - 1)
        return len(self.vector_store.documents) < before or doc is not None

    def chunks(self, filename: str, db=None, user_id: int | None = None) -> list[dict]:
        if db is not None:
            query = db.query(KnowledgeDocument).filter(KnowledgeDocument.filename == filename)
            if user_id is not None:
                query = query.filter(KnowledgeDocument.user_id == user_id)
            doc = query.first()
            if doc is None:
                return []
            rows = (
                db.query(KnowledgeChunk)
                .filter(KnowledgeChunk.doc_id == doc.id)
                .order_by(KnowledgeChunk.chunk_index)
                .all()
            )
            return [r.to_dict() for r in rows]
        return [
            {"chunk_index": d["metadata"].get("chunk_index"), "content": d["text"][:300]}
            for d in self.vector_store.documents
            if d["metadata"].get("filename") == filename
        ]

    def stats(self, db=None, user_id: int | None = None) -> dict:
        self._ensure_loaded(db)
        if db is not None and user_id is not None:
            docs = db.query(KnowledgeDocument).filter(KnowledgeDocument.user_id == user_id).all()
            return {
                "documents": len(docs),
                "chunks": sum(doc.chunk_count or 0 for doc in docs),
                "vocab_size": len(self.embedder.vocab),
            }
        return {
            "documents": self._docs_count,
            "chunks": len(self.vector_store.documents),
            "vocab_size": len(self.embedder.vocab),
        }


_kb = None

def get_global_kb() -> KnowledgeBase:
    """Process-wide singleton knowledge base."""
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb
