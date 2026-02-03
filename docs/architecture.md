# Code RAG Architecture для Apple M4 Max

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Code RAG System                                 │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐               │
│  │   Git Repo   │───>│  AST Chunker │───>│  Embedder    │               │
│  └──────────────┘    └──────────────┘    └──────────────┘               │
│         │                   │                   │                        │
│         │                   │                   ▼                        │
│         │                   │           ┌──────────────┐                 │
│         │                   │           │   Qdrant     │                 │
│         │                   │           │              │                 │
│         │                   │           │ ┌──────────┐ │                 │
│         │                   │           │ │  FILES   │ │                 │
│         │                   │           │ └──────────┘ │                 │
│         │                   │           │ ┌──────────┐ │                 │
│         │                   │           │ │ SYMBOLS  │ │                 │
│         │                   │           │ └──────────┘ │                 │
│         │                   │           │ ┌──────────┐ │                 │
│         │                   │           │ │ SEMANTIC │ │                 │
│         │                   │           │ └──────────┘ │                 │
│         │                   │           │ ┌──────────┐ │                 │
│         │                   │           │ │ PATTERNS │ │                 │
│         │                   │           │ └──────────┘ │                 │
│         │                   │           └──────────────┘                 │
│         │                   │                   │                        │
│         │                   │                   ▼                        │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐               │
│  │ Incremental  │<───│   Hybrid     │<───│   Context    │               │
│  │   Indexer    │    │   Search     │    │  Assembler   │               │
│  └──────────────┘    └──────────────┘    └──────────────┘               │
│                             │                   │                        │
│                             ▼                   ▼                        │
│                      ┌──────────────────────────────┐                   │
│                      │        LLM (Claude)          │                   │
│                      └──────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Multi-Level Index Architecture

### Level 1: FILES Collection
**Назначение:** Быстрый поиск по метаданным файлов

| Field | Type | Index |
|-------|------|-------|
| path | keyword | yes |
| filename | text | yes |
| language | keyword | yes |
| imports | keyword[] | no |
| symbols | keyword[] | no |
| git_hash | keyword | yes |
| modified_at | integer | yes |

**Use cases:**
- "Какие файлы работают с API?"
- "Найди файлы с импортом numpy"
- "Покажи структуру проекта"

### Level 2: SYMBOLS Collection
**Назначение:** Поиск функций, классов, методов по имени и сигнатуре

| Field | Type | Index |
|-------|------|-------|
| symbol_name | text | yes |
| symbol_type | keyword | yes |
| parent_symbol | keyword | yes |
| signature | text | no |
| docstring | text | no |
| file_path | keyword | yes |
| complexity | integer | yes |

**Use cases:**
- "Найди функцию process_data"
- "Покажи все методы класса User"
- "Где определен AuthService?"

### Level 3: SEMANTIC Collection
**Назначение:** Семантический поиск по коду

| Field | Type | Index |
|-------|------|-------|
| content | - | vector |
| chunk_type | keyword | yes |
| symbol_name | keyword | yes |
| file_path | keyword | yes |
| start_line | integer | yes |
| end_line | integer | yes |
| tokens | integer | yes |

**Use cases:**
- "Как реализована авторизация?"
- "Найди код для работы с базой данных"
- "Покажи примеры обработки ошибок"

### Level 4: PATTERNS Collection
**Назначение:** Паттерны кодирования, конвенции проекта

| Field | Type | Index |
|-------|------|-------|
| pattern_type | keyword | yes |
| name | text | yes |
| description | text | no |
| example_code | - | vector |
| usage_count | integer | yes |

**Use cases:**
- "Как в проекте логируют ошибки?"
- "Какой паттерн для API endpoints?"
- "Покажи примеры тестов"

---

## Performance Benchmarks (M4 Max, 128GB RAM)

### Embedding Performance

| Model | Dimensions | Throughput | Memory |
|-------|-----------|------------|--------|
| nomic-embed-text | 768 | 300 docs/sec | 1 GB |
| mxbai-embed-large | 1024 | 200 docs/sec | 1.5 GB |
| voyage-code-3 (API) | 1024 | 100 docs/sec | - |

### Indexing Performance

| Operation | Time | Notes |
|-----------|------|-------|
| Full index (10K files) | ~3 min | Parallel chunking + embedding |
| Incremental (100 files) | ~10 sec | Git-aware delta |
| Single file re-index | ~100 ms | Real-time updates |

### Search Latency

| Query Type | P50 | P95 | P99 |
|------------|-----|-----|-----|
| Exact symbol | 5 ms | 10 ms | 20 ms |
| Keyword search | 15 ms | 30 ms | 50 ms |
| Semantic search | 30 ms | 60 ms | 100 ms |
| Hybrid + rerank | 80 ms | 150 ms | 250 ms |

### Memory Usage

| Component | Memory |
|-----------|--------|
| Qdrant (100K vectors) | 2-4 GB |
| Embedding model | 1-1.5 GB |
| AST parser | 200 MB |
| Index state | 50 MB |
| **Total** | **~6 GB** |

---

## Chunking Strategy

### Chunk Size Guidelines

```
┌─────────────────────────────────────────────────────┐
│              Chunk Size Sweet Spot                   │
├─────────────────────────────────────────────────────┤
│                                                      │
│  Too Small (<50 tokens)     Too Large (>1000 tokens)│
│  ├─ Loss of context         ├─ Diluted relevance    │
│  ├─ Fragmented results      ├─ Token waste          │
│  └─ More embeddings         └─ Harder to rank       │
│                                                      │
│         ┌──────────────────────────┐                │
│         │   OPTIMAL: 200-500       │                │
│         │   tokens per chunk       │                │
│         └──────────────────────────┘                │
│                                                      │
└─────────────────────────────────────────────────────┘
```

### AST-Based Chunking Rules

1. **Functions/Methods:** One chunk if <500 tokens, split by blocks otherwise
2. **Classes:** Header + docstring as one chunk, methods separate
3. **Modules:** Imports + module docstring as one chunk
4. **Blocks:** Split large functions by logical blocks (if/for/try)
5. **Overlap:** 3 lines between adjacent chunks

---

## Hybrid Search Algorithm

```python
def hybrid_search(query, limit=10):
    # 1. Dense search (semantic)
    dense_results = vector_search(
        query_embedding,
        collection="code_semantic",
        limit=limit * 3
    )

    # 2. Sparse search (keyword/BM25)
    sparse_results = sparse_search(
        query_tokens,
        collection="code_semantic",
        limit=limit * 3
    )

    # 3. RRF Fusion
    combined = rrf_fusion(
        dense_results,
        sparse_results,
        k=60  # RRF constant
    )

    # 4. Re-ranking (optional)
    if enable_rerank:
        combined = cross_encoder_rerank(
            query,
            combined[:limit * 2]
        )

    # 5. Deduplication
    final = deduplicate_overlapping(combined)

    return final[:limit]
```

### RRF Formula

```
RRF_score(d) = Σ 1 / (k + rank_i(d))

where:
- k = 60 (constant)
- rank_i(d) = rank of document d in result list i
```

---

## Context Assembly Strategy

### Token Budget Allocation

```
┌────────────────────────────────────────┐
│       Context Window (8000 tokens)     │
├────────────────────────────────────────┤
│ ┌────────────────────────────────────┐ │
│ │ Definitions (25%)      2000 tokens │ │
│ │ ├─ Function signatures             │ │
│ │ ├─ Class definitions               │ │
│ │ └─ Type hints                      │ │
│ └────────────────────────────────────┘ │
│ ┌────────────────────────────────────┐ │
│ │ Relevant Code (55%)    4400 tokens │ │
│ │ ├─ Search results                  │ │
│ │ ├─ Implementation details          │ │
│ │ └─ Usage examples                  │ │
│ └────────────────────────────────────┘ │
│ ┌────────────────────────────────────┐ │
│ │ Context (15%)          1200 tokens │ │
│ │ ├─ File structure                  │ │
│ │ ├─ Imports                         │ │
│ │ └─ Related files                   │ │
│ └────────────────────────────────────┘ │
│ ┌────────────────────────────────────┐ │
│ │ Patterns (5%)           400 tokens │ │
│ │ └─ Project conventions             │ │
│ └────────────────────────────────────┘ │
└────────────────────────────────────────┘
```

### Deduplication Algorithm

```python
def deduplicate(chunks):
    result = []
    for chunk in sorted(chunks, key=lambda c: c.score, reverse=True):
        overlaps = False
        for existing in result:
            if same_file(chunk, existing):
                if lines_overlap(chunk, existing):
                    overlaps = True
                    # Keep higher-scored chunk
                    break
        if not overlaps:
            result.append(chunk)
    return result
```

---

## Incremental Indexing Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Incremental Update Flow                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  1. Load State                                                       │
│     └─> .rag_index_state.json                                       │
│         ├─ last_commit: "abc123"                                    │
│         └─ indexed_files: {"file.py": "hash123", ...}               │
│                                                                      │
│  2. Detect Changes                                                   │
│     └─> git diff abc123..HEAD                                       │
│         ├─ Added: new_file.py                                       │
│         ├─ Modified: changed_file.py                                │
│         ├─ Deleted: old_file.py                                     │
│         └─ Renamed: old_name.py -> new_name.py                      │
│                                                                      │
│  3. Update Index                                                     │
│     ├─ DELETE chunks where file_path = old_file.py                  │
│     ├─ DELETE chunks where file_path = changed_file.py              │
│     ├─ INSERT new chunks for changed_file.py                        │
│     ├─ INSERT new chunks for new_file.py                            │
│     └─ UPDATE file_path for renamed files                           │
│                                                                      │
│  4. Save State                                                       │
│     └─> .rag_index_state.json                                       │
│         ├─ last_commit: "def456"                                    │
│         └─ indexed_files: {updated map}                             │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Query Patterns by Use Case

### 1. Find Function Definition
```python
query = SearchQuery(
    text="process_data",
    mode=SearchMode.EXACT,
    symbol_types=["function", "method"],
)
results = search(query, collection="code_symbols")
```

### 2. Find Similar Code
```python
query = SearchQuery(
    text="async function that fetches data from API and handles errors",
    mode=SearchMode.SEMANTIC,
    min_score=0.7,
)
results = search(query, collection="code_semantic")
```

### 3. Find All Usages
```python
query = SearchQuery(
    text="UserService",
    mode=SearchMode.KEYWORD,
    exclude_paths=["tests/", "docs/"],
)
results = search(query, collection="code_semantic")
```

### 4. Find by Pattern
```python
query = SearchQuery(
    text="error handling with retry logic",
    mode=SearchMode.SEMANTIC,
)
results = search(query, collection="code_patterns")
```

### 5. Context-Aware Search
```python
# Search in current file context
query = SearchQuery(
    text="helper function for data validation",
    mode=SearchMode.HYBRID,
    file_paths=[current_file],  # Prioritize current file
)
results = multi_level_search(query)
```

---

## Recommended Stack

### Embedding
- **Primary:** `nomic-embed-text` via Ollama (fast, good quality)
- **Alternative:** `mxbai-embed-large` for higher dimensions
- **Premium:** `voyage-code-3` via API (best quality)

### Vector Database
- **Qdrant** (local Docker or native)
  - Hybrid search out of box
  - Good performance on M4
  - Rust-based, memory efficient

### AST Parsing
- **tree-sitter** (fast, reliable)
  - Native support for 40+ languages
  - Incremental parsing

### Re-ranking
- **cross-encoder/ms-marco-MiniLM-L-6-v2** (local)
- **Cohere Rerank** (API, best quality)

### Token Counting
- **tiktoken** (cl100k_base for Claude)
