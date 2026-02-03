# Code RAG System - Quick Start Guide

Локальная RAG-система для кодовой базы, оптимизированная для Apple M4 Max.

## Что это?

Code RAG - это система для семантического поиска по коду с:
- **AST-based chunking** - понимает структуру кода
- **Multi-level indexing** - 4 уровня для разных запросов
- **Hybrid search** - dense + sparse + reranking
- **Incremental updates** - git-aware индексация

## Quick Start

### 1. Запуск Qdrant

```bash
docker run -d \
  --name qdrant \
  -p 6333:6333 \
  -v ~/qdrant_data:/qdrant/storage \
  qdrant/qdrant
```

### 2. Установка Ollama + embedding модель

```bash
brew install ollama
ollama serve &
ollama pull nomic-embed-text
```

### 3. Установка зависимостей

```bash
cd ~/ai-projects/claude-auto-dev
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Индексация

```bash
python src/main.py /path/to/your/repo --index
```

### 5. Поиск

```bash
python src/main.py /path/to/repo --search "authentication handler"
```

## Использование в коде

```python
from src.main import CodeRAG, SearchMode

# Инициализация
rag = CodeRAG("/path/to/repo")
await rag.initialize()

# Индексация
await rag.index()

# Поиск
results = await rag.search(
    "how to handle API errors",
    mode=SearchMode.HYBRID,
    limit=10
)

# Сборка контекста для LLM
context = rag.assemble_context(results, query)
prompt = context.to_prompt()
```

## Файловая структура

```
src/
├── chunking/
│   └── ast_chunker.py      # AST-based chunking
├── indexing/
│   ├── qdrant_schema.py    # Qdrant collections
│   └── incremental_indexer.py
├── search/
│   └── hybrid_search.py    # Hybrid search
├── context/
│   └── context_assembler.py
└── main.py

docs/
├── architecture.md         # Полная архитектура
└── embedding_models.md     # Выбор моделей
```

## Performance (M4 Max)

| Метрика | Значение |
|---------|----------|
| Full index (10K файлов) | ~3 мин |
| Incremental (100 файлов) | ~10 сек |
| Hybrid search | ~80 ms |
| Memory | ~6 GB |

## Документация

- [Полная архитектура](architecture.md)
- [Выбор embedding моделей](embedding_models.md)
