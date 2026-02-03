"""
Hybrid Search Engine для Code RAG.

Комбинирует:
1. Dense vector search (семантика)
2. Sparse vector search (BM25/keywords)
3. Reciprocal Rank Fusion (RRF)
4. Cross-encoder re-ranking
"""

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Callable, Any
import numpy as np
from qdrant_client import QdrantClient, models
from qdrant_client.models import (
    Filter,
    FieldCondition,
    MatchValue,
    Range,
    ScoredPoint,
    Prefetch,
    Query,
)


class SearchMode(Enum):
    """Режимы поиска для разных use cases."""
    SEMANTIC = "semantic"       # Только dense vectors
    KEYWORD = "keyword"         # Только sparse/keyword
    HYBRID = "hybrid"           # Dense + Sparse + RRF
    EXACT = "exact"             # Точное совпадение имени


@dataclass
class SearchQuery:
    """Запрос на поиск."""
    text: str                              # Текст запроса
    mode: SearchMode = SearchMode.HYBRID   # Режим поиска
    limit: int = 10                        # Количество результатов
    min_score: float = 0.5                 # Минимальный score

    # Фильтры
    file_paths: Optional[list[str]] = None      # Ограничить файлами
    languages: Optional[list[str]] = None       # Языки
    symbol_types: Optional[list[str]] = None    # function, class, method
    exclude_paths: Optional[list[str]] = None   # Исключить пути

    # Опции
    with_payload: bool = True
    with_vectors: bool = False
    rerank: bool = True         # Использовать re-ranking
    deduplicate: bool = True    # Дедупликация overlapping chunks


@dataclass
class SearchResult:
    """Результат поиска."""
    id: str
    score: float
    content: str
    file_path: str
    start_line: int
    end_line: int
    symbol_name: Optional[str] = None
    chunk_type: Optional[str] = None
    payload: dict = field(default_factory=dict)

    # Для дедупликации
    def overlaps_with(self, other: "SearchResult") -> bool:
        """Проверяет перекрытие с другим результатом."""
        if self.file_path != other.file_path:
            return False
        return not (self.end_line < other.start_line or self.start_line > other.end_line)


class HybridSearchEngine:
    """
    Hybrid Search Engine с поддержкой:
    - Multi-stage retrieval (coarse-to-fine)
    - RRF fusion для dense+sparse
    - Cross-encoder re-ranking
    - Context-aware deduplication
    """

    # RRF constant (стандартное значение)
    RRF_K = 60

    def __init__(
        self,
        qdrant_client: QdrantClient,
        embed_fn: Callable[[str], np.ndarray],
        sparse_embed_fn: Optional[Callable[[str], tuple[list[int], list[float]]]] = None,
        rerank_fn: Optional[Callable[[str, list[str]], list[float]]] = None,
    ):
        """
        Args:
            qdrant_client: Клиент Qdrant
            embed_fn: Функция для dense embeddings
            sparse_embed_fn: Функция для sparse embeddings (indices, values)
            rerank_fn: Cross-encoder для re-ranking
        """
        self.client = qdrant_client
        self.embed = embed_fn
        self.sparse_embed = sparse_embed_fn
        self.rerank = rerank_fn

    async def search(
        self,
        query: SearchQuery,
        collection: str = "code_semantic",
    ) -> list[SearchResult]:
        """
        Выполняет поиск в зависимости от режима.

        Returns:
            Отсортированный список SearchResult
        """
        # 1. Построение фильтров
        filter_conditions = self._build_filters(query)

        # 2. Выбор стратегии поиска
        if query.mode == SearchMode.EXACT:
            results = await self._exact_search(query, collection, filter_conditions)
        elif query.mode == SearchMode.KEYWORD:
            results = await self._keyword_search(query, collection, filter_conditions)
        elif query.mode == SearchMode.SEMANTIC:
            results = await self._semantic_search(query, collection, filter_conditions)
        else:  # HYBRID
            results = await self._hybrid_search(query, collection, filter_conditions)

        # 3. Re-ranking (если включен и есть функция)
        if query.rerank and self.rerank and len(results) > 1:
            results = await self._rerank_results(query.text, results)

        # 4. Дедупликация
        if query.deduplicate:
            results = self._deduplicate_results(results)

        # 5. Фильтрация по min_score
        results = [r for r in results if r.score >= query.min_score]

        return results[:query.limit]

    async def _hybrid_search(
        self,
        query: SearchQuery,
        collection: str,
        filter_conditions: Optional[Filter],
    ) -> list[SearchResult]:
        """
        Hybrid search с RRF fusion.

        Использует Qdrant Query API для multi-stage retrieval:
        1. Prefetch dense results
        2. Prefetch sparse results
        3. RRF fusion
        """
        # Получаем embeddings
        dense_vector = self.embed(query.text)

        # Формируем prefetch запросы
        prefetch_queries = [
            # Dense search - семантика
            Prefetch(
                query=dense_vector.tolist(),
                using="dense",
                limit=query.limit * 3,  # Больше для fusion
                filter=filter_conditions,
            ),
        ]

        # Добавляем sparse если есть
        if self.sparse_embed:
            indices, values = self.sparse_embed(query.text)
            prefetch_queries.append(
                Prefetch(
                    query=models.SparseVector(
                        indices=indices,
                        values=values,
                    ),
                    using="sparse",
                    limit=query.limit * 3,
                    filter=filter_conditions,
                ),
            )

        # Выполняем query с RRF fusion
        response = self.client.query_points(
            collection_name=collection,
            prefetch=prefetch_queries,
            query=Query(
                fusion=models.Fusion.RRF,  # Reciprocal Rank Fusion
            ),
            limit=query.limit * 2,  # Запас для re-ranking
            with_payload=query.with_payload,
            with_vectors=query.with_vectors,
        )

        return self._convert_results(response.points)

    async def _semantic_search(
        self,
        query: SearchQuery,
        collection: str,
        filter_conditions: Optional[Filter],
    ) -> list[SearchResult]:
        """Только dense vector search."""
        dense_vector = self.embed(query.text)

        response = self.client.query_points(
            collection_name=collection,
            query=dense_vector.tolist(),
            using="dense",
            limit=query.limit * 2,
            filter=filter_conditions,
            with_payload=query.with_payload,
        )

        return self._convert_results(response.points)

    async def _keyword_search(
        self,
        query: SearchQuery,
        collection: str,
        filter_conditions: Optional[Filter],
    ) -> list[SearchResult]:
        """Только sparse/keyword search."""
        if not self.sparse_embed:
            raise ValueError("Sparse embedding function not configured")

        indices, values = self.sparse_embed(query.text)

        response = self.client.query_points(
            collection_name=collection,
            query=models.SparseVector(indices=indices, values=values),
            using="sparse",
            limit=query.limit * 2,
            filter=filter_conditions,
            with_payload=query.with_payload,
        )

        return self._convert_results(response.points)

    async def _exact_search(
        self,
        query: SearchQuery,
        collection: str,
        filter_conditions: Optional[Filter],
    ) -> list[SearchResult]:
        """
        Точный поиск по имени символа.

        Использует payload filtering, не vectors.
        """
        # Добавляем условие на symbol_name
        name_condition = FieldCondition(
            key="symbol_name",
            match=MatchValue(value=query.text.lower()),
        )

        if filter_conditions:
            combined_filter = Filter(
                must=[*filter_conditions.must, name_condition]
                if filter_conditions.must
                else [name_condition]
            )
        else:
            combined_filter = Filter(must=[name_condition])

        response = self.client.scroll(
            collection_name=collection,
            scroll_filter=combined_filter,
            limit=query.limit,
            with_payload=query.with_payload,
        )

        # Scroll возвращает tuple (points, next_page_offset)
        points = response[0]

        return [
            SearchResult(
                id=str(p.id),
                score=1.0,  # Exact match
                content=p.payload.get("content", ""),
                file_path=p.payload.get("file_path", ""),
                start_line=p.payload.get("start_line", 0),
                end_line=p.payload.get("end_line", 0),
                symbol_name=p.payload.get("symbol_name"),
                chunk_type=p.payload.get("chunk_type"),
                payload=p.payload,
            )
            for p in points
        ]

    async def _rerank_results(
        self,
        query_text: str,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """
        Re-ranking с использованием cross-encoder.

        Cross-encoder оценивает пары (query, document) напрямую,
        что дает лучшее качество чем bi-encoder.
        """
        if not results:
            return results

        # Собираем тексты для re-ranking
        documents = [r.content for r in results]

        # Получаем новые scores
        new_scores = self.rerank(query_text, documents)

        # Обновляем scores и сортируем
        for result, score in zip(results, new_scores):
            result.score = score

        results.sort(key=lambda r: r.score, reverse=True)

        return results

    def _deduplicate_results(
        self,
        results: list[SearchResult],
    ) -> list[SearchResult]:
        """
        Удаляет перекрывающиеся чанки.

        Стратегия: оставляем чанк с более высоким score.
        """
        if not results:
            return results

        deduplicated = []

        for result in results:
            # Проверяем перекрытие с уже добавленными
            overlaps = False
            for existing in deduplicated:
                if result.overlaps_with(existing):
                    overlaps = True
                    # Можно объединить ranges если нужно
                    break

            if not overlaps:
                deduplicated.append(result)

        return deduplicated

    def _build_filters(self, query: SearchQuery) -> Optional[Filter]:
        """Строит Qdrant фильтры из query."""
        conditions = []

        # Фильтр по путям
        if query.file_paths:
            conditions.append(
                FieldCondition(
                    key="file_path",
                    match=models.MatchAny(any=query.file_paths),
                )
            )

        # Фильтр по языкам
        if query.languages:
            conditions.append(
                FieldCondition(
                    key="language",
                    match=models.MatchAny(any=query.languages),
                )
            )

        # Фильтр по типам символов
        if query.symbol_types:
            conditions.append(
                FieldCondition(
                    key="chunk_type",
                    match=models.MatchAny(any=query.symbol_types),
                )
            )

        # Исключение путей
        must_not = []
        if query.exclude_paths:
            for path in query.exclude_paths:
                must_not.append(
                    FieldCondition(
                        key="file_path",
                        match=MatchValue(value=path),
                    )
                )

        if not conditions and not must_not:
            return None

        return Filter(
            must=conditions if conditions else None,
            must_not=must_not if must_not else None,
        )

    def _convert_results(self, points: list[ScoredPoint]) -> list[SearchResult]:
        """Конвертирует Qdrant points в SearchResult."""
        return [
            SearchResult(
                id=str(p.id),
                score=p.score,
                content=p.payload.get("content", ""),
                file_path=p.payload.get("file_path", ""),
                start_line=p.payload.get("start_line", 0),
                end_line=p.payload.get("end_line", 0),
                symbol_name=p.payload.get("symbol_name"),
                chunk_type=p.payload.get("chunk_type"),
                payload=p.payload,
            )
            for p in points
        ]


# === Multi-Collection Search ===

class MultiLevelSearch:
    """
    Поиск по нескольким уровням индексации.

    Стратегия:
    1. Сначала ищем в SYMBOLS (функции, классы)
    2. Если не нашли - ищем в SEMANTIC (чанки кода)
    3. Объединяем с учетом relevance
    """

    def __init__(self, search_engine: HybridSearchEngine):
        self.engine = search_engine

    async def search_code(
        self,
        query: str,
        context: Optional[str] = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """
        Умный поиск кода.

        Args:
            query: Поисковый запрос
            context: Дополнительный контекст (текущий файл, etc)
            limit: Количество результатов
        """
        # Определяем режим поиска по query
        mode = self._detect_search_mode(query)

        # Создаем query object
        search_query = SearchQuery(
            text=query,
            mode=mode,
            limit=limit,
            rerank=True,
            deduplicate=True,
        )

        # Ищем в symbols
        symbol_results = await self.engine.search(
            search_query,
            collection="code_symbols",
        )

        # Если нашли точные совпадения - возвращаем их
        if symbol_results and symbol_results[0].score > 0.9:
            return symbol_results[:limit]

        # Ищем в semantic
        semantic_results = await self.engine.search(
            search_query,
            collection="code_semantic",
        )

        # Объединяем результаты
        combined = self._merge_results(symbol_results, semantic_results, limit)

        return combined

    def _detect_search_mode(self, query: str) -> SearchMode:
        """Определяет оптимальный режим поиска."""
        # Если query похож на имя функции/класса
        if self._looks_like_symbol_name(query):
            return SearchMode.EXACT

        # Если query содержит кодовые паттерны
        if any(c in query for c in ['()', '{}', '[]', '=>', '::']):
            return SearchMode.KEYWORD

        # По умолчанию hybrid
        return SearchMode.HYBRID

    def _looks_like_symbol_name(self, query: str) -> bool:
        """Проверяет, похож ли query на имя символа."""
        # Одно слово, snake_case или CamelCase
        if ' ' not in query:
            if '_' in query:  # snake_case
                return True
            if query[0].isupper():  # CamelCase
                return True
        return False

    def _merge_results(
        self,
        symbols: list[SearchResult],
        semantic: list[SearchResult],
        limit: int,
    ) -> list[SearchResult]:
        """Объединяет результаты из разных коллекций."""
        # Используем RRF для объединения
        rrf_scores: dict[str, float] = {}
        all_results: dict[str, SearchResult] = {}

        k = 60  # RRF constant

        # Scores от symbols (более важны)
        for rank, result in enumerate(symbols):
            score = 1.0 / (k + rank)  # RRF formula
            key = f"{result.file_path}:{result.start_line}"
            rrf_scores[key] = rrf_scores.get(key, 0) + score * 1.2  # Boost symbols
            all_results[key] = result

        # Scores от semantic
        for rank, result in enumerate(semantic):
            score = 1.0 / (k + rank)
            key = f"{result.file_path}:{result.start_line}"
            rrf_scores[key] = rrf_scores.get(key, 0) + score
            if key not in all_results:
                all_results[key] = result

        # Сортируем по RRF score
        sorted_keys = sorted(rrf_scores.keys(), key=lambda k: rrf_scores[k], reverse=True)

        results = []
        for key in sorted_keys[:limit]:
            result = all_results[key]
            result.score = rrf_scores[key]
            results.append(result)

        return results


# === Query Patterns для разных use cases ===

QUERY_PATTERNS = {
    # Поиск определения функции
    "find_function": {
        "mode": SearchMode.EXACT,
        "symbol_types": ["function", "method"],
        "collection": "code_symbols",
    },

    # Поиск использований функции
    "find_usages": {
        "mode": SearchMode.KEYWORD,
        "collection": "code_semantic",
        "boost_keyword": True,
    },

    # Семантический поиск "как сделать X"
    "how_to": {
        "mode": SearchMode.HYBRID,
        "collection": "code_semantic",
        "rerank": True,
    },

    # Поиск похожего кода
    "similar_code": {
        "mode": SearchMode.SEMANTIC,
        "collection": "code_semantic",
        "min_score": 0.7,
    },

    # Поиск класса и его методов
    "find_class": {
        "mode": SearchMode.EXACT,
        "symbol_types": ["class"],
        "collection": "code_symbols",
    },

    # Поиск импортов/зависимостей
    "find_imports": {
        "mode": SearchMode.KEYWORD,
        "chunk_types": ["module"],
        "collection": "code_semantic",
    },

    # Поиск паттернов (error handling, logging)
    "find_pattern": {
        "mode": SearchMode.SEMANTIC,
        "collection": "code_patterns",
    },
}
