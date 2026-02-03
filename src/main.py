"""
Code RAG System - Main Application.

Локальный RAG для кодовой базы с:
- AST-based chunking
- Multi-level indexing
- Hybrid search
- Incremental updates
"""

import asyncio
from pathlib import Path
from typing import Optional
import numpy as np

from qdrant_client import QdrantClient

# Local imports
from chunking.ast_chunker import ASTChunker
from indexing.qdrant_schema import QdrantSchemaManager, QdrantConfig
from indexing.incremental_indexer import IncrementalIndexer
from search.hybrid_search import HybridSearchEngine, MultiLevelSearch, SearchQuery, SearchMode
from context.context_assembler import ContextAssembler, AssembledContext


class CodeRAG:
    """
    Main Code RAG System.

    Usage:
        rag = CodeRAG("/path/to/repo")
        await rag.initialize()
        await rag.index()

        results = await rag.search("how to handle authentication")
        context = rag.assemble_context(results, query)
    """

    def __init__(
        self,
        repo_path: str | Path,
        qdrant_host: str = "localhost",
        qdrant_port: int = 6333,
        embedding_model: str = "nomic-embed-text",
        max_context_tokens: int = 8000,
    ):
        self.repo_path = Path(repo_path)
        self.embedding_model = embedding_model
        self.max_context_tokens = max_context_tokens

        # Qdrant client
        self.qdrant = QdrantClient(host=qdrant_host, port=qdrant_port)

        # Components (initialized later)
        self._chunker: Optional[ASTChunker] = None
        self._indexer: Optional[IncrementalIndexer] = None
        self._search_engine: Optional[HybridSearchEngine] = None
        self._multi_search: Optional[MultiLevelSearch] = None
        self._context_assembler: Optional[ContextAssembler] = None

        # Embedding function (set during initialize)
        self._embed_fn = None
        self._sparse_embed_fn = None
        self._rerank_fn = None

    async def initialize(self, create_collections: bool = True):
        """
        Инициализирует все компоненты.

        Args:
            create_collections: Создать коллекции в Qdrant
        """
        # 1. Setup embedding functions
        await self._setup_embeddings()

        # 2. Create Qdrant collections
        if create_collections:
            schema_manager = QdrantSchemaManager(
                host="localhost",
                port=6333,
                config=QdrantConfig(),
            )
            try:
                schema_manager.create_all_collections(recreate=False)
            except Exception:
                pass  # Collections may already exist

        # 3. Initialize components
        self._chunker = ASTChunker(language="python")

        self._indexer = IncrementalIndexer(
            repo_path=self.repo_path,
            qdrant_client=self.qdrant,
            chunker=self._chunker,
            embedder=self._embed_fn,
        )

        self._search_engine = HybridSearchEngine(
            qdrant_client=self.qdrant,
            embed_fn=self._embed_fn,
            sparse_embed_fn=self._sparse_embed_fn,
            rerank_fn=self._rerank_fn,
        )

        self._multi_search = MultiLevelSearch(self._search_engine)

        self._context_assembler = ContextAssembler(
            max_tokens=self.max_context_tokens,
        )

    async def _setup_embeddings(self):
        """Настраивает embedding функции."""
        if self.embedding_model == "nomic-embed-text":
            self._embed_fn = self._ollama_embed
            # Sparse через Qdrant built-in
            self._sparse_embed_fn = self._simple_sparse_embed
        else:
            # Fallback to sentence-transformers
            self._embed_fn = self._st_embed

    def _ollama_embed(self, text: str) -> np.ndarray:
        """Embedding через Ollama."""
        import requests

        response = requests.post(
            "http://localhost:11434/api/embeddings",
            json={
                "model": self.embedding_model,
                "prompt": text,
            },
        )
        data = response.json()
        return np.array(data["embedding"])

    def _st_embed(self, text: str) -> np.ndarray:
        """Embedding через sentence-transformers."""
        from sentence_transformers import SentenceTransformer

        if not hasattr(self, "_st_model"):
            self._st_model = SentenceTransformer("all-MiniLM-L6-v2")

        return self._st_model.encode(text)

    def _simple_sparse_embed(self, text: str) -> tuple[list[int], list[float]]:
        """
        Простой sparse embedding на основе TF.

        Для production лучше использовать SPLADE.
        """
        from collections import Counter
        import re

        # Токенизация
        tokens = re.findall(r'\w+', text.lower())

        # Term frequency
        tf = Counter(tokens)

        # Конвертируем в indices/values
        # Используем hash для indices (простой подход)
        indices = []
        values = []

        for token, count in tf.items():
            idx = hash(token) % 30000  # Vocabulary size
            indices.append(abs(idx))
            values.append(float(count))

        return indices, values

    # === Public API ===

    async def index(
        self,
        full: bool = False,
        extensions: list[str] = None,
    ) -> dict:
        """
        Индексирует репозиторий.

        Args:
            full: Полная переиндексация
            extensions: Фильтр расширений

        Returns:
            Статистика индексации
        """
        if not self._indexer:
            raise RuntimeError("Call initialize() first")

        return await self._indexer.index(
            full_reindex=full,
            extensions=extensions,
        )

    async def search(
        self,
        query: str,
        limit: int = 10,
        mode: SearchMode = SearchMode.HYBRID,
        **kwargs,
    ) -> list:
        """
        Поиск по кодовой базе.

        Args:
            query: Поисковый запрос
            limit: Количество результатов
            mode: Режим поиска

        Returns:
            Список SearchResult
        """
        if not self._multi_search:
            raise RuntimeError("Call initialize() first")

        search_query = SearchQuery(
            text=query,
            mode=mode,
            limit=limit,
            **kwargs,
        )

        return await self._multi_search.search_code(query, limit=limit)

    def assemble_context(
        self,
        search_results: list,
        query: str,
    ) -> AssembledContext:
        """
        Собирает контекст для LLM.

        Args:
            search_results: Результаты поиска
            query: Оригинальный запрос

        Returns:
            AssembledContext
        """
        if not self._context_assembler:
            raise RuntimeError("Call initialize() first")

        return self._context_assembler.assemble(
            search_results=search_results,
            query=query,
        )

    async def query(
        self,
        question: str,
        limit: int = 10,
    ) -> tuple[list, AssembledContext]:
        """
        Полный pipeline: search + context assembly.

        Returns:
            (search_results, assembled_context)
        """
        results = await self.search(question, limit=limit)
        context = self.assemble_context(results, question)
        return results, context


# === CLI Interface ===

async def main():
    """CLI для Code RAG."""
    import argparse

    parser = argparse.ArgumentParser(description="Code RAG System")
    parser.add_argument("repo", help="Path to repository")
    parser.add_argument("--index", action="store_true", help="Index the repository")
    parser.add_argument("--full", action="store_true", help="Full re-index")
    parser.add_argument("--search", type=str, help="Search query")
    parser.add_argument("--limit", type=int, default=10, help="Number of results")

    args = parser.parse_args()

    # Initialize
    rag = CodeRAG(args.repo)
    await rag.initialize()

    if args.index:
        print(f"Indexing {args.repo}...")
        stats = await rag.index(full=args.full)
        print(f"Indexed {stats.get('files_indexed', 0)} files")
        print(f"Created {stats.get('chunks_created', 0)} chunks")
        if stats.get("errors"):
            print(f"Errors: {len(stats['errors'])}")

    if args.search:
        print(f"\nSearching: {args.search}")
        results, context = await rag.query(args.search, limit=args.limit)

        print(f"\nFound {len(results)} results:")
        for i, r in enumerate(results[:5], 1):
            print(f"\n{i}. {r.file_path}:{r.start_line}-{r.end_line}")
            print(f"   Score: {r.score:.3f}")
            print(f"   Symbol: {r.symbol_name or 'N/A'}")
            print(f"   Preview: {r.content[:100]}...")

        print(f"\nContext assembled: {context.total_tokens} tokens")
        print(f"Files included: {context.files_included}")
        print(f"Budget used: {context.budget_used:.1%}")


if __name__ == "__main__":
    asyncio.run(main())
