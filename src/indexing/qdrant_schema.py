"""
Qdrant Schema для Multi-Level Code Indexing.

Создает оптимизированные коллекции для разных уровней поиска.
"""

from dataclasses import dataclass
from enum import Enum
from qdrant_client import QdrantClient, models
from qdrant_client.models import (
    VectorParams,
    SparseVectorParams,
    Distance,
    HnswConfigDiff,
    OptimizersConfigDiff,
    PayloadSchemaType,
    TokenizerType,
    TextIndexParams,
    TextIndexType,
)


# === Конфигурация ===

@dataclass
class QdrantConfig:
    """Конфигурация Qdrant для M4 Max."""

    # Размерности embedding
    DENSE_DIM: int = 768          # nomic-embed-text
    DENSE_DIM_LARGE: int = 1024   # mxbai-embed-large

    # HNSW параметры (оптимизированы для 128GB RAM)
    HNSW_M: int = 32              # Больше связей = лучше recall
    HNSW_EF_CONSTRUCT: int = 200  # Качество построения
    HNSW_EF_SEARCH: int = 128     # Качество поиска

    # Оптимизация
    MEMMAP_THRESHOLD_KB: int = 50000  # Держим в RAM до 50MB
    INDEXING_THRESHOLD: int = 5000    # Начинаем индексировать после 5k vectors

    # Segment configuration
    MAX_SEGMENT_SIZE: int = 100000    # Векторов на сегмент


class CollectionName(Enum):
    """Имена коллекций для разных уровней."""
    FILES = "code_files"           # File-level metadata
    SYMBOLS = "code_symbols"       # Functions, classes, methods
    SEMANTIC = "code_semantic"     # Semantic chunks
    PATTERNS = "code_patterns"     # Coding patterns


class QdrantSchemaManager:
    """
    Управляет схемой Qdrant для Code RAG.

    Multi-level индексация:
    1. FILES - быстрый поиск по метаданным файлов
    2. SYMBOLS - поиск функций/классов по имени и сигнатуре
    3. SEMANTIC - семантический поиск по коду
    4. PATTERNS - паттерны и конвенции кодирования
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        config: QdrantConfig = None
    ):
        self.client = QdrantClient(host=host, port=port)
        self.config = config or QdrantConfig()

    def create_all_collections(self, recreate: bool = False):
        """Создает все коллекции."""
        self.create_files_collection(recreate)
        self.create_symbols_collection(recreate)
        self.create_semantic_collection(recreate)
        self.create_patterns_collection(recreate)

    def create_files_collection(self, recreate: bool = False):
        """
        Коллекция FILE-level.

        Хранит метаданные файлов для быстрой навигации.
        Использует только sparse vectors (keyword search).
        """
        name = CollectionName.FILES.value

        if recreate:
            self.client.delete_collection(name)

        self.client.create_collection(
            collection_name=name,
            vectors_config={
                # Dense vector для семантики описания файла
                "dense": VectorParams(
                    size=self.config.DENSE_DIM,
                    distance=Distance.COSINE,
                    hnsw_config=HnswConfigDiff(
                        m=16,  # Меньше для файлов (их немного)
                        ef_construct=100,
                    ),
                    on_disk=False,  # Держим в RAM
                ),
            },
            sparse_vectors_config={
                # Sparse для keyword search по путям и именам
                "sparse": SparseVectorParams(
                    modifier=models.Modifier.IDF,  # TF-IDF weighting
                ),
            },
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=1000,  # Файлов обычно мало
            ),
        )

        # Payload индексы для фильтрации
        self._create_file_payload_indexes(name)

    def create_symbols_collection(self, recreate: bool = False):
        """
        Коллекция SYMBOL-level.

        Хранит функции, классы, методы.
        Hybrid search: dense + sparse.
        """
        name = CollectionName.SYMBOLS.value

        if recreate:
            self.client.delete_collection(name)

        self.client.create_collection(
            collection_name=name,
            vectors_config={
                # Dense для семантики сигнатуры + docstring
                "dense": VectorParams(
                    size=self.config.DENSE_DIM,
                    distance=Distance.COSINE,
                    hnsw_config=HnswConfigDiff(
                        m=self.config.HNSW_M,
                        ef_construct=self.config.HNSW_EF_CONSTRUCT,
                    ),
                    on_disk=False,  # Символы в RAM
                ),
            },
            sparse_vectors_config={
                # Sparse для имен функций, параметров
                "sparse": SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=self.config.INDEXING_THRESHOLD,
                memmap_threshold=self.config.MEMMAP_THRESHOLD_KB,
            ),
        )

        self._create_symbol_payload_indexes(name)

    def create_semantic_collection(self, recreate: bool = False):
        """
        Коллекция SEMANTIC-level.

        Основная коллекция для семантического поиска по коду.
        Самая большая - использует все оптимизации.
        """
        name = CollectionName.SEMANTIC.value

        if recreate:
            self.client.delete_collection(name)

        self.client.create_collection(
            collection_name=name,
            vectors_config={
                # Основной dense vector
                "dense": VectorParams(
                    size=self.config.DENSE_DIM,
                    distance=Distance.COSINE,
                    hnsw_config=HnswConfigDiff(
                        m=self.config.HNSW_M,
                        ef_construct=self.config.HNSW_EF_CONSTRUCT,
                    ),
                    # Для больших объемов - на диск
                    on_disk=True,
                    # Quantization для экономии памяти
                    quantization_config=models.ScalarQuantization(
                        scalar=models.ScalarQuantizationConfig(
                            type=models.ScalarType.INT8,
                            quantile=0.99,
                            always_ram=True,  # Quantized в RAM
                        ),
                    ),
                ),
                # Matryoshka: уменьшенный vector для быстрого pre-filtering
                "dense_small": VectorParams(
                    size=256,  # Matryoshka dimension
                    distance=Distance.COSINE,
                    hnsw_config=HnswConfigDiff(
                        m=16,
                        ef_construct=64,
                    ),
                    on_disk=False,  # Маленький - в RAM
                ),
            },
            sparse_vectors_config={
                "sparse": SparseVectorParams(
                    modifier=models.Modifier.IDF,
                ),
            },
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=self.config.INDEXING_THRESHOLD,
                memmap_threshold=self.config.MEMMAP_THRESHOLD_KB,
                max_segment_number=4,  # Параллелизм на M4
            ),
        )

        self._create_semantic_payload_indexes(name)

    def create_patterns_collection(self, recreate: bool = False):
        """
        Коллекция PATTERN-level.

        Хранит паттерны кодирования, конвенции, типичные решения.
        Используется для suggestions и обучения стилю проекта.
        """
        name = CollectionName.PATTERNS.value

        if recreate:
            self.client.delete_collection(name)

        self.client.create_collection(
            collection_name=name,
            vectors_config={
                "dense": VectorParams(
                    size=self.config.DENSE_DIM,
                    distance=Distance.COSINE,
                    hnsw_config=HnswConfigDiff(
                        m=24,
                        ef_construct=128,
                    ),
                    on_disk=False,
                ),
            },
            optimizers_config=OptimizersConfigDiff(
                indexing_threshold=500,  # Паттернов немного
            ),
        )

        self._create_pattern_payload_indexes(name)

    # === Payload Indexes ===

    def _create_file_payload_indexes(self, collection: str):
        """Индексы для FILES коллекции."""

        # Путь к файлу - keyword
        self.client.create_payload_index(
            collection_name=collection,
            field_name="path",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Имя файла - text search
        self.client.create_payload_index(
            collection_name=collection,
            field_name="filename",
            field_schema=TextIndexParams(
                type=TextIndexType.TEXT,
                tokenizer=TokenizerType.WORD,
                lowercase=True,
            ),
        )

        # Язык программирования
        self.client.create_payload_index(
            collection_name=collection,
            field_name="language",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Git hash для версионирования
        self.client.create_payload_index(
            collection_name=collection,
            field_name="git_hash",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Timestamp последнего изменения
        self.client.create_payload_index(
            collection_name=collection,
            field_name="modified_at",
            field_schema=PayloadSchemaType.INTEGER,
        )

    def _create_symbol_payload_indexes(self, collection: str):
        """Индексы для SYMBOLS коллекции."""

        # Тип символа (function, class, method)
        self.client.create_payload_index(
            collection_name=collection,
            field_name="symbol_type",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Имя символа - важно для точного поиска
        self.client.create_payload_index(
            collection_name=collection,
            field_name="symbol_name",
            field_schema=TextIndexParams(
                type=TextIndexType.TEXT,
                tokenizer=TokenizerType.WORD,  # split by underscore, camelCase
                lowercase=True,
            ),
        )

        # Родительский символ (для методов)
        self.client.create_payload_index(
            collection_name=collection,
            field_name="parent_symbol",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Путь к файлу
        self.client.create_payload_index(
            collection_name=collection,
            field_name="file_path",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Язык
        self.client.create_payload_index(
            collection_name=collection,
            field_name="language",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Сложность (для фильтрации)
        self.client.create_payload_index(
            collection_name=collection,
            field_name="complexity",
            field_schema=PayloadSchemaType.INTEGER,
        )

    def _create_semantic_payload_indexes(self, collection: str):
        """Индексы для SEMANTIC коллекции."""

        # Тип чанка
        self.client.create_payload_index(
            collection_name=collection,
            field_name="chunk_type",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Путь к файлу
        self.client.create_payload_index(
            collection_name=collection,
            field_name="file_path",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Диапазон строк (для дедупликации)
        self.client.create_payload_index(
            collection_name=collection,
            field_name="start_line",
            field_schema=PayloadSchemaType.INTEGER,
        )

        self.client.create_payload_index(
            collection_name=collection,
            field_name="end_line",
            field_schema=PayloadSchemaType.INTEGER,
        )

        # Язык
        self.client.create_payload_index(
            collection_name=collection,
            field_name="language",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Количество токенов (для budget management)
        self.client.create_payload_index(
            collection_name=collection,
            field_name="tokens",
            field_schema=PayloadSchemaType.INTEGER,
        )

        # Связанный символ
        self.client.create_payload_index(
            collection_name=collection,
            field_name="symbol_name",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Git hash
        self.client.create_payload_index(
            collection_name=collection,
            field_name="git_hash",
            field_schema=PayloadSchemaType.KEYWORD,
        )

    def _create_pattern_payload_indexes(self, collection: str):
        """Индексы для PATTERNS коллекции."""

        # Тип паттерна
        self.client.create_payload_index(
            collection_name=collection,
            field_name="pattern_type",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Язык/фреймворк
        self.client.create_payload_index(
            collection_name=collection,
            field_name="language",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        self.client.create_payload_index(
            collection_name=collection,
            field_name="framework",
            field_schema=PayloadSchemaType.KEYWORD,
        )

        # Частота использования
        self.client.create_payload_index(
            collection_name=collection,
            field_name="usage_count",
            field_schema=PayloadSchemaType.INTEGER,
        )


# === Payload Schemas (для документации) ===

FILE_PAYLOAD_SCHEMA = {
    "id": "string - уникальный ID",
    "path": "string - абсолютный путь",
    "filename": "string - имя файла",
    "language": "string - python, javascript, etc",
    "imports": "list[string] - импорты",
    "symbols": "list[string] - все символы в файле",
    "git_hash": "string - последний commit hash",
    "modified_at": "int - unix timestamp",
    "size_bytes": "int - размер файла",
}

SYMBOL_PAYLOAD_SCHEMA = {
    "id": "string - уникальный ID чанка",
    "symbol_type": "string - function, class, method",
    "symbol_name": "string - имя символа",
    "parent_symbol": "string? - родитель (для методов)",
    "file_path": "string - путь к файлу",
    "start_line": "int",
    "end_line": "int",
    "signature": "string - полная сигнатура",
    "docstring": "string? - документация",
    "language": "string",
    "complexity": "int - cyclomatic complexity",
    "calls": "list[string] - вызываемые функции",
    "dependencies": "list[string] - зависимости",
}

SEMANTIC_PAYLOAD_SCHEMA = {
    "id": "string - уникальный ID",
    "chunk_type": "string - file, module, class, method, function, block",
    "file_path": "string",
    "start_line": "int",
    "end_line": "int",
    "content": "string - исходный код",
    "symbol_name": "string? - связанный символ",
    "parent_symbol": "string?",
    "language": "string",
    "tokens": "int - количество токенов",
    "git_hash": "string",
}

PATTERN_PAYLOAD_SCHEMA = {
    "id": "string",
    "pattern_type": "string - error_handling, logging, testing, etc",
    "name": "string - название паттерна",
    "description": "string - описание",
    "example_code": "string - пример кода",
    "language": "string",
    "framework": "string? - fastapi, django, etc",
    "usage_count": "int - сколько раз встречается",
    "file_paths": "list[string] - где встречается",
}


if __name__ == "__main__":
    # Создаем все коллекции
    manager = QdrantSchemaManager()
    manager.create_all_collections(recreate=True)
    print("All collections created successfully!")
