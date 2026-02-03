# Embedding Models для Code RAG

## Основные модели (локальные)

### 1. CodeSage (рекомендуется)
- **Модель:** `codesage-large-v2` (1024 dims)
- **Размер:** ~1.3GB
- **Производительность:** ~100 embeddings/sec на M4 Max
- **Плюсы:** Специализирована на коде, понимает 20+ языков

### 2. Voyage Code (API, высшее качество)
- **Модель:** `voyage-code-3` (1024 dims)
- **Качество:** Лучшее для code retrieval
- **Минус:** Требует API, не локальная

### 3. BGE-Code (локальная альтернатива)
- **Модель:** `BAAI/bge-code-embedder-v1.5` (768 dims)
- **Размер:** ~500MB
- **Производительность:** ~200 embeddings/sec

### 4. Nomic Embed (хороший баланс)
- **Модель:** `nomic-ai/nomic-embed-text-v1.5` (768 dims)
- **Размер:** ~550MB
- **Плюсы:** Matryoshka embeddings (можно уменьшать dims)

## Sparse модель для BM25
- **SPLADE:** `naver/splade-cocondenser-ensembledistil`
- **Или встроенный Qdrant BM25** (проще в настройке)

## Рекомендация для M4 Max

Использовать **два embedding пайплайна**:

1. **Dense:** `nomic-embed-text-v1.5` через Ollama
   - Быстрый, качественный для общего кода

2. **Sparse:** Встроенный Qdrant sparse vectors
   - Для keyword matching (имена функций, переменных)

## Запуск через Ollama

```bash
# Установка моделей
ollama pull nomic-embed-text
ollama pull mxbai-embed-large  # Альтернатива 1024 dims
```

## Производительность на M4 Max

| Модель | Dimensions | Throughput | RAM |
|--------|-----------|------------|-----|
| nomic-embed-text | 768 | ~300/sec | 1GB |
| mxbai-embed-large | 1024 | ~200/sec | 1.5GB |
| all-minilm-l6 | 384 | ~500/sec | 400MB |

## Matryoshka Embeddings

Nomic поддерживает Matryoshka - можно хранить полные 768 dims,
но искать по 256 для скорости, потом re-rank по полным.
