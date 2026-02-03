"""
Context Assembler для LLM.

Собирает оптимальный контекст из результатов поиска:
1. Relevance scoring
2. Token budget management
3. Deduplication
4. Context ordering
"""

import tiktoken
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from pathlib import Path


class ContextPriority(Enum):
    """Приоритеты для разных типов контекста."""
    CRITICAL = 1.0      # Точное совпадение запроса
    HIGH = 0.8          # Определение функции/класса
    MEDIUM = 0.6        # Связанный код
    LOW = 0.4           # Контекст файла
    BACKGROUND = 0.2    # Общая информация


@dataclass
class ContextChunk:
    """Единица контекста для LLM."""
    content: str
    file_path: str
    start_line: int
    end_line: int
    priority: ContextPriority
    relevance_score: float
    token_count: int

    # Метаданные
    symbol_name: Optional[str] = None
    chunk_type: Optional[str] = None
    is_definition: bool = False

    @property
    def effective_score(self) -> float:
        """Комбинированный score для сортировки."""
        return self.relevance_score * self.priority.value


@dataclass
class AssembledContext:
    """Собранный контекст для LLM."""
    chunks: list[ContextChunk]
    total_tokens: int
    budget_used: float  # Процент использованного бюджета

    # Статистика
    files_included: int
    symbols_included: int
    truncated_chunks: int

    def to_prompt(self) -> str:
        """Форматирует контекст для промпта."""
        sections = []

        # Группируем по файлам
        by_file: dict[str, list[ContextChunk]] = {}
        for chunk in self.chunks:
            if chunk.file_path not in by_file:
                by_file[chunk.file_path] = []
            by_file[chunk.file_path].append(chunk)

        for file_path, file_chunks in by_file.items():
            # Сортируем чанки по строкам
            file_chunks.sort(key=lambda c: c.start_line)

            sections.append(f"# File: {file_path}")

            for chunk in file_chunks:
                if chunk.symbol_name:
                    sections.append(f"## {chunk.symbol_name} (lines {chunk.start_line}-{chunk.end_line})")
                else:
                    sections.append(f"## Lines {chunk.start_line}-{chunk.end_line}")

                sections.append("```")
                sections.append(chunk.content)
                sections.append("```")
                sections.append("")

        return "\n".join(sections)


class ContextAssembler:
    """
    Собирает оптимальный контекст для LLM.

    Стратегия:
    1. Сортировка по relevance * priority
    2. Добавление определений для упомянутых символов
    3. Token budget management с truncation
    4. Дедупликация перекрывающихся чанков
    5. Умный ordering (definitions before usages)
    """

    def __init__(
        self,
        max_tokens: int = 8000,
        model: str = "cl100k_base",  # Для Claude/GPT-4
        reserve_tokens: int = 1000,   # Резерв для системного промпта
    ):
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens
        self.tokenizer = tiktoken.get_encoding(model)

    def assemble(
        self,
        search_results: list,  # SearchResult from hybrid_search
        query: str,
        include_definitions: bool = True,
        include_file_context: bool = True,
    ) -> AssembledContext:
        """
        Собирает контекст из результатов поиска.

        Args:
            search_results: Результаты поиска
            query: Оригинальный запрос (для приоритизации)
            include_definitions: Добавлять определения символов
            include_file_context: Добавлять контекст файла
        """
        # 1. Конвертируем в ContextChunk с приоритетами
        chunks = self._create_chunks(search_results, query)

        # 2. Добавляем definitions если нужно
        if include_definitions:
            chunks = self._add_definitions(chunks)

        # 3. Дедупликация
        chunks = self._deduplicate(chunks)

        # 4. Сортировка по effective score
        chunks.sort(key=lambda c: c.effective_score, reverse=True)

        # 5. Token budget management
        selected_chunks, stats = self._apply_budget(chunks)

        # 6. Ordering: definitions first, then usages
        ordered_chunks = self._order_for_prompt(selected_chunks)

        return AssembledContext(
            chunks=ordered_chunks,
            total_tokens=stats["total_tokens"],
            budget_used=stats["budget_used"],
            files_included=stats["files"],
            symbols_included=stats["symbols"],
            truncated_chunks=stats["truncated"],
        )

    def _create_chunks(
        self,
        search_results: list,
        query: str,
    ) -> list[ContextChunk]:
        """Создает ContextChunk из SearchResult."""
        chunks = []

        for result in search_results:
            # Определяем приоритет
            priority = self._determine_priority(result, query)

            # Считаем токены
            token_count = self._count_tokens(result.content)

            chunks.append(ContextChunk(
                content=result.content,
                file_path=result.file_path,
                start_line=result.start_line,
                end_line=result.end_line,
                priority=priority,
                relevance_score=result.score,
                token_count=token_count,
                symbol_name=result.symbol_name,
                chunk_type=result.chunk_type,
                is_definition=result.chunk_type in ("function", "class", "method"),
            ))

        return chunks

    def _determine_priority(self, result, query: str) -> ContextPriority:
        """Определяет приоритет чанка."""
        # Точное совпадение имени
        if result.symbol_name and result.symbol_name.lower() in query.lower():
            return ContextPriority.CRITICAL

        # Определение функции/класса
        if result.chunk_type in ("function", "class", "method"):
            return ContextPriority.HIGH

        # Высокий score от поиска
        if result.score > 0.8:
            return ContextPriority.HIGH

        # Средний score
        if result.score > 0.6:
            return ContextPriority.MEDIUM

        return ContextPriority.LOW

    def _add_definitions(self, chunks: list[ContextChunk]) -> list[ContextChunk]:
        """
        Добавляет определения для упомянутых символов.

        Если в чанке используется функция X, добавляем её определение.
        """
        # TODO: Реализовать через дополнительный поиск в symbols collection
        # Пока возвращаем as is
        return chunks

    def _deduplicate(self, chunks: list[ContextChunk]) -> list[ContextChunk]:
        """Удаляет перекрывающиеся чанки."""
        if not chunks:
            return chunks

        # Сортируем по score (чтобы оставлять лучшие)
        sorted_chunks = sorted(chunks, key=lambda c: c.effective_score, reverse=True)

        deduplicated = []
        for chunk in sorted_chunks:
            overlaps = False
            for existing in deduplicated:
                if self._chunks_overlap(chunk, existing):
                    overlaps = True
                    # Если новый чанк больше и содержит existing - заменяем
                    if self._chunk_contains(chunk, existing):
                        deduplicated.remove(existing)
                        deduplicated.append(chunk)
                    break

            if not overlaps:
                deduplicated.append(chunk)

        return deduplicated

    def _chunks_overlap(self, a: ContextChunk, b: ContextChunk) -> bool:
        """Проверяет перекрытие чанков."""
        if a.file_path != b.file_path:
            return False
        return not (a.end_line < b.start_line or a.start_line > b.end_line)

    def _chunk_contains(self, outer: ContextChunk, inner: ContextChunk) -> bool:
        """Проверяет, содержит ли outer чанк inner."""
        if outer.file_path != inner.file_path:
            return False
        return outer.start_line <= inner.start_line and outer.end_line >= inner.end_line

    def _apply_budget(
        self,
        chunks: list[ContextChunk],
    ) -> tuple[list[ContextChunk], dict]:
        """
        Применяет token budget.

        Стратегия:
        1. Добавляем чанки по приоритету
        2. Если чанк не влезает целиком - truncate
        3. Оставляем резерв для системного промпта
        """
        available_tokens = self.max_tokens - self.reserve_tokens
        used_tokens = 0
        selected = []
        truncated_count = 0

        for chunk in chunks:
            if used_tokens >= available_tokens:
                break

            remaining = available_tokens - used_tokens

            if chunk.token_count <= remaining:
                # Влезает целиком
                selected.append(chunk)
                used_tokens += chunk.token_count
            elif remaining > 100:  # Минимум для truncated chunk
                # Truncate
                truncated = self._truncate_chunk(chunk, remaining)
                selected.append(truncated)
                used_tokens += truncated.token_count
                truncated_count += 1

        # Статистика
        unique_files = len(set(c.file_path for c in selected))
        unique_symbols = len(set(c.symbol_name for c in selected if c.symbol_name))

        stats = {
            "total_tokens": used_tokens,
            "budget_used": used_tokens / self.max_tokens,
            "files": unique_files,
            "symbols": unique_symbols,
            "truncated": truncated_count,
        }

        return selected, stats

    def _truncate_chunk(
        self,
        chunk: ContextChunk,
        max_tokens: int,
    ) -> ContextChunk:
        """Truncate чанк до заданного количества токенов."""
        tokens = self.tokenizer.encode(chunk.content)
        truncated_tokens = tokens[:max_tokens - 10]  # Резерв для "..."
        truncated_content = self.tokenizer.decode(truncated_tokens) + "\n... (truncated)"

        return ContextChunk(
            content=truncated_content,
            file_path=chunk.file_path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,  # Может быть неточным
            priority=chunk.priority,
            relevance_score=chunk.relevance_score,
            token_count=max_tokens,
            symbol_name=chunk.symbol_name,
            chunk_type=chunk.chunk_type,
            is_definition=chunk.is_definition,
        )

    def _order_for_prompt(
        self,
        chunks: list[ContextChunk],
    ) -> list[ContextChunk]:
        """
        Упорядочивает чанки для промпта.

        Порядок:
        1. Definitions (функции, классы)
        2. Usages (по relevance)
        3. Background context (по файлам)
        """
        definitions = [c for c in chunks if c.is_definition]
        non_definitions = [c for c in chunks if not c.is_definition]

        # Definitions сортируем по имени для consistency
        definitions.sort(key=lambda c: (c.file_path, c.symbol_name or ""))

        # Non-definitions по relevance
        non_definitions.sort(key=lambda c: c.effective_score, reverse=True)

        return definitions + non_definitions

    def _count_tokens(self, text: str) -> int:
        """Считает токены в тексте."""
        return len(self.tokenizer.encode(text))


# === Token Budget Strategies ===

class TokenBudgetStrategy(Enum):
    """Стратегии распределения token budget."""

    # Равномерное распределение
    UNIFORM = "uniform"

    # Больше токенов на релевантные чанки
    RELEVANCE_WEIGHTED = "relevance_weighted"

    # Приоритет definitions
    DEFINITIONS_FIRST = "definitions_first"

    # Приоритет текущему файлу
    CURRENT_FILE_FIRST = "current_file_first"


@dataclass
class BudgetAllocation:
    """Распределение бюджета по категориям."""
    definitions: int = 2000     # Определения функций/классов
    relevant: int = 4000        # Релевантный код
    context: int = 1500         # Контекст файла
    patterns: int = 500         # Паттерны/примеры


# === Context Window Optimizer ===

class ContextWindowOptimizer:
    """
    Оптимизирует использование context window.

    Для Claude 3.5 / GPT-4 с большим контекстом
    использует стратегию "stuffing with intelligence".
    """

    def __init__(
        self,
        model_context_window: int = 128000,  # Claude 3.5
        target_utilization: float = 0.6,      # Целевое использование
    ):
        self.context_window = model_context_window
        self.target_utilization = target_utilization

    def calculate_budget(
        self,
        system_prompt_tokens: int,
        expected_output_tokens: int,
        strategy: TokenBudgetStrategy = TokenBudgetStrategy.RELEVANCE_WEIGHTED,
    ) -> BudgetAllocation:
        """
        Рассчитывает бюджет для контекста.

        Args:
            system_prompt_tokens: Токены системного промпта
            expected_output_tokens: Ожидаемый размер ответа
        """
        # Доступный бюджет
        available = self.context_window - system_prompt_tokens - expected_output_tokens
        target = int(available * self.target_utilization)

        if strategy == TokenBudgetStrategy.DEFINITIONS_FIRST:
            return BudgetAllocation(
                definitions=int(target * 0.35),
                relevant=int(target * 0.45),
                context=int(target * 0.15),
                patterns=int(target * 0.05),
            )

        elif strategy == TokenBudgetStrategy.RELEVANCE_WEIGHTED:
            return BudgetAllocation(
                definitions=int(target * 0.25),
                relevant=int(target * 0.55),
                context=int(target * 0.15),
                patterns=int(target * 0.05),
            )

        else:  # UNIFORM
            quarter = target // 4
            return BudgetAllocation(
                definitions=quarter,
                relevant=quarter,
                context=quarter,
                patterns=quarter,
            )
