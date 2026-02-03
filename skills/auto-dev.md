# Auto-Dev: Hybrid Multi-Agent Development Orchestrator

Автономная мультиагентная система разработки с гарантией качества.

**Использование:** `/auto-dev <описание задачи>`

---

## 🔄 Workflow Overview

```
TASK → [ROUTING] → [DISCOVER] → [PLAN] → [BUILD] → [TEST] → [REVIEW] → [SECURITY] → [VISUAL QA] → [DEPLOY]
```

---

## Phase 0: Smart Routing (Claude-Flow)

**Цель:** Определить тип задачи и выбрать оптимальную стратегию.

### Действия:

1. **Определить тип workflow:**
   ```bash
   claude-flow hooks route --task "$TASK_DESCRIPTION"
   ```

2. **Выбрать модель для фазы:**
   ```bash
   claude-flow hooks model-route --task "$TASK_DESCRIPTION"
   ```

3. **Загрузить релевантные паттерны:**
   ```bash
   claude-flow memory search --query "$TASK_DESCRIPTION" --limit 5
   ```

### Решения на основе routing:

| Workflow Type | Фазы | Когда |
|--------------|------|-------|
| `feature` | Все 8 | Новая функциональность |
| `bugfix` | 1,3,4,5,8 | Исправление ошибки |
| `refactor` | 1,2,3,4,5 | Рефакторинг |
| `docs` | 1,3,5,8 | Документация |
| `test` | 1,3,4 | Только тесты |

---

## Phase 1: DISCOVER

**Цель:** Понять кодовую базу и контекст задачи.

### Действия:

1. Запустить **Explore агента** для анализа:
   - Структура проекта
   - Связанные файлы
   - Существующие паттерны
   - Tech stack

2. Загрузить **Serena memories** если есть релевантные:
   ```
   mcp__serena__list_memories()
   mcp__serena__read_memory("relevant_memory")
   ```

### Gate: Discovery Complete
- [ ] Найдены релевантные файлы
- [ ] Tech stack определён
- [ ] Паттерны задокументированы

---

## Phase 2: PLAN

**Цель:** Создать детальный план реализации.

### Действия:

1. Запустить **Plan агента**:
   - Декомпозиция на задачи
   - Определение зависимостей
   - Идентификация рисков

2. Создать **Task list** через TaskCreate:
   ```
   TaskCreate для каждой подзадачи
   TaskUpdate для зависимостей (addBlockedBy)
   ```

### ⭐ HUMAN CHECKPOINT: Plan Approval

Показать пользователю:
- План реализации
- Список задач
- Оценка рисков

Спросить: **Одобрить / Изменить / Отменить**

---

## Phase 3: BUILD

**Цель:** Реализовать код согласно плану.

### Действия:

1. **Model selection** для каждой задачи:
   ```bash
   claude-flow hooks model-route --task "задача"
   ```

2. **Выбрать агента** на основе routing:
   - `backend-architect` — для API, backend
   - `frontend-developer` — для UI
   - `python-pro` / `fastapi-pro` — для Python
   - `database-architect` — для DB

3. **Параллельное выполнение** независимых задач:
   - Использовать Task tool с run_in_background
   - Ждать завершения всех

4. **Learning hooks:**
   ```bash
   claude-flow hooks pre-task --task-id "id"
   # ... выполнение ...
   claude-flow hooks post-task --task-id "id" --success true
   ```

### Gate: Build Complete
- [ ] Все задачи выполнены
- [ ] Нет синтаксических ошибок
- [ ] Код компилируется

---

## Phase 4: TEST

**Цель:** Написать и запустить тесты.

### Действия:

1. Запустить **test-automator** агента:
   - Написание unit тестов
   - Coverage analysis

2. При failures — запустить **debugger** агента

3. **Retry logic:**
   - Max 5 попыток
   - debugger → fix → retest
   - Если не удалось — эскалация к human

### Gate: Tests Passing
- [ ] Все тесты проходят
- [ ] Coverage >= 80%
- [ ] Нет регрессий

---

## Phase 5: REVIEW

**Цель:** Проверить качество кода.

### Действия:

Последовательно запустить:

1. **code-reviewer** — общее качество, паттерны
2. **silent-failure-hunter** — ошибки обработки
3. **type-design-analyzer** — качество типов (если TypeScript/typed Python)

### Retry logic:
- Исправить critical/high issues
- Перезапустить review
- Max 3 попытки

### Gate: Review Passed
- [ ] Нет critical issues
- [ ] Нет high issues

---

## Phase 6: SECURITY ⚠️

**Цель:** Проверить безопасность изменений.

### Действия:

1. Запустить **security-auditor** агента:
   - OWASP Top 10 checks
   - Secrets detection
   - Dependency audit

2. Также можно использовать:
   ```bash
   claude-flow security scan
   ```

### ⚠️ ESCALATION: При critical vulnerabilities
- Немедленно уведомить пользователя
- Предоставить детали и рекомендации
- Ждать решения

### Gate: Security Cleared
- [ ] Нет critical vulnerabilities
- [ ] Нет high vulnerabilities
- [ ] Secrets не экспонированы

---

## Phase 7: VISUAL QA (Conditional)

**Условие:** Только если есть frontend изменения.

### Действия:

1. Использовать **visual-qa MCP**:
   ```
   visual_qa_check — скриншоты
   visual_qa_compare — сравнение с baseline
   visual_qa_audit_clickables — проверка интерактивных элементов
   ```

2. Accessibility audit

### Gate: Visual QA Passed
- [ ] Нет visual regressions
- [ ] Accessibility OK

---

## Phase 8: DEPLOY

**Цель:** Создать PR или задеплоить.

### ⭐ HUMAN CHECKPOINT: Deploy Approval

Показать пользователю:
- Summary изменений
- Результаты тестов
- Review summary
- Security report

Спросить: **Deploy / PR only / Staging / Hold**

### Действия по выбору:

**PR only:**
1. `git checkout -b feature/...`
2. `git add` изменённые файлы
3. `git commit` с детальным сообщением
4. `git push -u origin branch`
5. `gh pr create` с полным описанием

**Deploy:**
1. Создать PR
2. Merge после CI
3. Monitor deployment

### Post-Deploy:

1. **Сохранить паттерны:**
   ```bash
   claude-flow memory store --key "pattern_..." --value "..." --namespace patterns
   ```

2. **Записать в Serena:**
   ```
   mcp__serena__write_memory("session_...", "details")
   ```

3. Обновить CHANGELOG если significant

---

## 🛡️ Quality Gates Summary

| Phase | Gate | Criteria | Retry |
|-------|------|----------|-------|
| 1 | Discovery Complete | files found, stack identified | 2 |
| 2 | Plan Approved | **HUMAN** | - |
| 3 | Build Complete | tasks done, compiles | 3 |
| 4 | Tests Passing | all pass, coverage ≥80% | 5 |
| 5 | Review Passed | no critical/high | 3 |
| 6 | Security Cleared | no vulnerabilities | 3 |
| 7 | Visual QA Passed | no regressions | 2 |
| 8 | Deploy Approved | **HUMAN** | - |

---

## 🔧 Quick Reference

### Claude-Flow Commands:
```bash
# Routing
claude-flow hooks route --task "..."
claude-flow hooks model-route --task "..."

# Memory
claude-flow memory search --query "..."
claude-flow memory store --key "..." --value "..."

# Learning
claude-flow hooks pre-task --task-id "..."
claude-flow hooks post-task --task-id "..." --success true

# Metrics
claude-flow hooks metrics
```

### Task Tools:
```
TaskCreate — создать задачу
TaskUpdate — обновить статус
TaskList — список задач
TaskGet — детали задачи
```

### Agents:
- Explore, Plan — discovery & planning
- backend-architect, frontend-developer — build
- test-automator, debugger — testing
- code-reviewer, silent-failure-hunter — review
- security-auditor — security

---

## 📝 Example Usage

```
/auto-dev Добавить endpoint для экспорта отчётов в PDF

[ROUTING] → feature workflow, fastapi-pro agent, sonnet model
[DISCOVER] → Found reports/ module, existing export patterns
[PLAN] → 4 tasks created, estimated 30 min
  ⭐ Approve plan? [Yes]
[BUILD] → PDF generator, endpoint, tests created
[TEST] → 5/5 passing, 87% coverage
[REVIEW] → OK
[SECURITY] → OK
[DEPLOY] →
  ⭐ Action? [Create PR]

✅ PR created: https://github.com/user/repo/pull/42
```

---

*Version: 1.0.0 | Hybrid Integration: Claude-Flow v3 + Custom Gates*
