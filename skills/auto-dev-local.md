# Auto-Dev Local: Полностью локальная мультиагентная система

Автономная разработка **без интернета** с локальными LLM.

**Использование:** `/auto-dev-local <описание задачи>`

---

## 🔄 Workflow

```
TASK → [CLASSIFY] → [PLAN] → ⭐APPROVE → [BUILD] → [REVIEW] → [TEST] → ⭐DEPLOY
```

---

## Проверка системы

Перед началом проверь:

```bash
# 1. Ollama запущен
curl http://localhost:11434/api/tags

# 2. Основные модели есть
ollama list | grep -E "qwen3-coder|deepseek-r1"

# 3. Embedding модель
ollama list | grep nomic-embed
```

---

## Phase 1: CLASSIFY

**Быстрая классификация задачи**

Используй модель `qwen3:8b` для определения:
- Тип: feature / bugfix / refactor / docs / test
- Сложность: simple / medium / complex
- Нужна ли архитектура
- Нужны ли тесты

---

## Phase 2: PLAN

**Декомпозиция на подзадачи**

Используй модель `deepseek-r1:32b` для создания плана:

1. Разбить задачу на подзадачи
2. Определить зависимости
3. Выбрать агентов для каждой подзадачи
4. Оценить время

### Агенты:

| Агент | Модель | Задачи |
|-------|--------|--------|
| **Architect** | deepseek-r1:32b | Design, ADR, planning |
| **Coder** | qwen3-coder:30b | Implementation, refactoring |
| **Reviewer** | deepseek-r1:32b | Code review, security |
| **Tester** | qwen3-coder:30b | Unit tests, coverage |
| **Docs** | qwen3:8b | Documentation |

---

## ⭐ CHECKPOINT: Plan Approval

Показать пользователю:
- Список задач
- Зависимости (Mermaid диаграмма)
- Оценка времени
- Модели которые будут использоваться

**Спросить:** Одобрить / Изменить / Отменить

---

## Phase 3: BUILD

**Выполнение задач**

### Выбор модели для задачи:

```python
TASK_MODEL_MAPPING = {
    "architecture": "deepseek-r1:32b",
    "implementation": "qwen3-coder:30b",
    "refactoring": "qwen3-coder:30b",
    "review": "deepseek-r1:32b",
    "testing": "qwen3-coder:30b",
    "documentation": "qwen3:8b",
}
```

### Параллельное выполнение:

- Независимые задачи выполняются параллельно
- Зависимые — последовательно
- Retry при неудаче (до 3 раз)

### RAG для контекста:

Если контекст большой:
1. Использовать `nomic-embed-text` для embeddings
2. Поиск релевантного кода в Qdrant
3. Собрать контекст в пределах 32K токенов

---

## Phase 4: REVIEW

**Code Review**

Используй агента **Reviewer** (deepseek-r1:32b) для проверки:

### Чеклист:
- [ ] Security (input validation, auth, secrets)
- [ ] Code quality (readability, error handling)
- [ ] Architecture (patterns, separation of concerns)
- [ ] Performance

### Формат:
```
🚫 BLOCKING: [обязательно исправить]
⚠️ WARNING: [желательно исправить]
💡 SUGGESTION: [на усмотрение]
✅ GOOD: [что хорошо]
```

---

## Phase 5: TEST

**Тестирование**

Используй агента **Tester** (qwen3-coder:30b):

1. Написать unit тесты
2. Запустить тесты
3. Проверить coverage

### Gates:
- [ ] Все тесты проходят
- [ ] Coverage >= 80%

---

## ⭐ CHECKPOINT: Deploy Approval

Показать пользователю:
- Summary изменений
- Результаты review
- Результаты тестов
- Статистика (токены, время)

**Спросить:** Deploy / PR only / Hold

---

## Phase 6: DEPLOY

По выбору пользователя:

**Commit:**
```bash
git add [изменённые файлы]
git commit -m "feat: описание"
```

**PR:**
```bash
git checkout -b feature/...
git push -u origin feature/...
gh pr create
```

---

## 🔧 Локальные команды

### Проверка моделей:
```bash
ollama list
```

### Загрузка модели:
```bash
ollama pull qwen3-coder:30b
ollama pull deepseek-r1:32b
```

### Запуск inference:
```bash
ollama run qwen3-coder:30b "напиши функцию"
```

### RAG индексация:
```bash
python ~/ai-projects/claude-auto-dev/src/main.py . --index
```

---

## 📊 Performance на M4 Max 128GB

| Операция | Время |
|----------|-------|
| Классификация (8B) | ~1-2 сек |
| Декомпозиция (32B) | ~10-20 сек |
| Генерация кода (30B) | ~20-60 сек |
| Review (32B) | ~15-30 сек |
| **Полный цикл фичи** | **2-5 мин** |

---

## 📝 Пример

```
/auto-dev-local Добавить endpoint /api/users/{id} для получения пользователя

[CLASSIFY] feature, medium, needs_testing=true
[PLAN] 4 задачи создано:
  1. [architecture] Спроектировать endpoint
  2. [implementation] Реализовать handler
  3. [testing] Написать тесты
  4. [documentation] Обновить API docs

⭐ Approve plan? [Yes]

[BUILD]
  ✅ task_1: Architecture (deepseek-r1:32b) - 12s
  ✅ task_2: Implementation (qwen3-coder:30b) - 25s
  ✅ task_3: Testing (qwen3-coder:30b) - 18s
  ✅ task_4: Documentation (qwen3:8b) - 8s

[REVIEW] ✅ No blocking issues

[TEST] ✅ 5/5 tests passed, 92% coverage

⭐ Deploy? [Commit]

✅ Committed: feat: Add GET /api/users/{id} endpoint
```

---

## ⚠️ Troubleshooting

### Ollama не отвечает
```bash
ollama serve
```

### Модель не найдена
```bash
ollama pull qwen3-coder:30b
```

### Не хватает RAM
```bash
# Закрыть тяжёлые приложения
# Использовать меньшую модель
ollama run qwen3:8b
```

### Медленная генерация
```bash
# Проверить GPU использование
sudo powermetrics --samplers gpu_power
```

---

*Version: 1.0.0 | Fully Offline Multi-Agent System*
