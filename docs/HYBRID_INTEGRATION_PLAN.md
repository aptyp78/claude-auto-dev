# Гибридная интеграция: Claude-Flow + Наш Workflow

> **Дата:** 2026-02-03
> **Статус:** Планирование
> **Версия claude-flow:** 3.1.0-alpha.3

---

## 1. Концепция гибридного подхода

```
┌─────────────────────────────────────────────────────────────────────┐
│                    HYBRID ORCHESTRATOR                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                   CLAUDE-FLOW LAYER                          │    │
│  │  • Q-Learning routing (hooks_route)                          │    │
│  │  • Model selection (hooks_model-route)                       │    │
│  │  • HNSW memory search (memory_search)                        │    │
│  │  • Agent spawning (agent_spawn)                              │    │
│  │  • Learning (hooks_pre-task, hooks_post-task)                │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                             │                                         │
│                             ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                   OUR WORKFLOW LAYER                         │    │
│  │  • 8-phase pipeline (Discover → Deploy)                      │    │
│  │  • Quality Gates with retry                                  │    │
│  │  • Security Phase (security-auditor)                         │    │
│  │  • Visual QA Phase (visual-qa MCP)                           │    │
│  │  • Human Checkpoints (plan, deploy)                          │    │
│  │  • Serena long-term memory                                   │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Что берём от claude-flow

### 2.1 Intelligent Routing

```yaml
# Вместо статичного выбора агента
before: "Всегда использовать backend-architect для Python"

# Используем Q-Learning routing
after:
  tool: hooks_route
  input:
    task: "Добавить endpoint для PDF export"
    context: "FastAPI project, existing reports module"
  output:
    agent: "fastapi-pro"
    confidence: 0.87
    reasoning: "Similar tasks in history used fastapi-pro with 92% success"
```

### 2.2 Model Selection

```yaml
# Автоматический выбор модели
tool: hooks_model-route
input:
  task_type: "code_review"
  complexity: "medium"
output:
  model: "sonnet"  # Не Opus для review — экономия
  reason: "Code review doesn't require deep reasoning"
```

### 2.3 Memory & Learning

```yaml
# После каждой успешной задачи
tool: hooks_post-task
input:
  task_id: "task_123"
  success: true
  agent_used: "fastapi-pro"
  time_taken: 45
  files_changed: 3

# Система учится и улучшает routing
```

### 2.4 HNSW Vector Search

```yaml
# Поиск похожих паттернов из прошлого
tool: memory_search
input:
  query: "OAuth implementation FastAPI"
  limit: 5
output:
  - pattern: "oauth_fastapi_pattern_v1"
    similarity: 0.94
    content: "Use httpx-oauth with dependency injection..."
```

---

## 3. Что остаётся нашим

### 3.1 Security Phase (уникально)

Claude-flow имеет `security` команду, но:
- Нет интеграции с security-auditor agent
- Нет обязательного gate перед deploy
- Нет escalation к human при critical

**Наша реализация:**
```yaml
phase_security:
  mandatory: true
  agents: [security-auditor]
  gate:
    block_on:
      - critical_vulnerabilities > 0
      - high_vulnerabilities > 0
    escalate_to_human:
      - any critical found
```

### 3.2 Visual QA Phase (уникально)

Claude-flow **не имеет** visual testing.

**Наша интеграция:**
```yaml
phase_visual_qa:
  condition: "has_frontend_changes"
  mcp_server: "visual-qa"
  tools:
    - visual_qa_check
    - visual_qa_compare
    - visual_qa_audit_clickables
  gate:
    pass_criteria:
      - no_visual_regressions
      - accessibility_ok
```

### 3.3 Human Checkpoints (улучшено)

Claude-flow имеет human-in-loop, но ad-hoc.

**Наша структура:**
```yaml
human_checkpoints:
  after_plan:
    required: true
    display: [plan, tasks, risks]
    options: [approve, modify, reject]

  before_deploy:
    required: true
    display: [changes, tests, security, review]
    options: [deploy, pr_only, staging, hold]
```

### 3.4 Serena Long-term Memory

Claude-flow имеет `memory_store`, но:
- SQLite/AgentDB — только текущая сессия
- Нет cross-project knowledge

**Наша интеграция:**
```yaml
memory_strategy:
  session_memory: "claude-flow memory_*"  # Быстрый поиск
  persistent_memory: "Serena"              # Cross-session, cross-project

  sync_triggers:
    - session_end
    - significant_decision
    - successful_pattern
```

---

## 4. Архитектура интеграции

### 4.1 Новый workflow

```
/auto-dev "Добавить авторизацию OAuth"
    │
    ▼
┌─────────────────────────────────────┐
│  PHASE 0: SMART ROUTING             │
│  • hooks_pretrain (если новый проект)│
│  • hooks_route → выбор workflow     │
│  • hooks_model-route → выбор модели │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  PHASE 1: DISCOVER                  │
│  • memory_search (похожие паттерны) │
│  • Explore agents                   │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  PHASE 2: PLAN                      │
│  • Plan agent (routed model)        │
│  • hooks_pre-task (learning)        │
│  ★ HUMAN CHECKPOINT                 │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  PHASE 3: BUILD                     │
│  • agent_spawn (если нужно)         │
│  • Workers (routed agents)          │
│  • hooks_post-task (learning)       │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  PHASE 4: TEST                      │
│  • test-automator                   │
│  • debugger (if failures)           │
│  ✓ QUALITY GATE: coverage ≥ 80%     │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  PHASE 5: REVIEW                    │
│  • code-reviewer                    │
│  • silent-failure-hunter            │
│  ✓ QUALITY GATE: no critical/high   │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  PHASE 6: SECURITY (UNIQUE)         │
│  • security-auditor                 │
│  ✓ QUALITY GATE: no vulnerabilities │
│  ⚠ ESCALATE if critical             │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  PHASE 7: VISUAL QA (UNIQUE)        │
│  • visual-qa MCP                    │
│  • Conditional: frontend changes    │
│  ✓ QUALITY GATE: no regressions     │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  PHASE 8: DEPLOY                    │
│  ★ HUMAN CHECKPOINT                 │
│  • memory_store (save patterns)     │
│  • Serena write_memory              │
│  • git/GitHub operations            │
└─────────────────────────────────────┘
```

### 4.2 Использование claude-flow tools

| Фаза | Claude-flow tool | Назначение |
|------|-----------------|------------|
| 0 | `hooks_pretrain` | Bootstrap для нового проекта |
| 0 | `hooks_route` | Выбор workflow type |
| 0 | `hooks_model-route` | Выбор модели для фазы |
| 1 | `memory_search` | Поиск похожих паттернов |
| 2+ | `hooks_pre-task` | Начало задачи (learning) |
| 2+ | `hooks_post-task` | Конец задачи (learning) |
| 3 | `agent_spawn` | Создание воркеров если нужно |
| 8 | `memory_store` | Сохранение паттернов |

---

## 5. Конфигурация

### 5.1 Глобальная конфигурация

**Файл:** `~/.claude/orchestrator.yaml`

```yaml
orchestrator:
  version: "1.0"

  # Гибридный режим
  hybrid:
    enabled: true
    claude_flow:
      routing: true       # hooks_route
      model_selection: true  # hooks_model-route
      learning: true      # hooks_pre/post-task
      memory: true        # memory_* tools
    our_workflow:
      security_phase: true
      visual_qa_phase: true
      human_checkpoints: true
      serena_memory: true

  # Quality Gates
  gates:
    test_coverage: 80
    max_retries: 5

  # Human checkpoints
  checkpoints:
    plan_approval: required
    deploy_approval: required
```

### 5.2 Режимы работы

```yaml
modes:
  # Полный режим — все фичи
  full:
    phases: [discover, plan, build, test, review, security, visual_qa, deploy]
    claude_flow: all

  # Быстрый режим — skip learning
  fast:
    phases: [discover, plan, build, test, deploy]
    claude_flow: [routing, memory_search]
    skip: [learning, visual_qa]

  # Минимальный — только код
  minimal:
    phases: [build, test]
    claude_flow: none
```

---

## 6. План реализации

### Этап 1: Базовая интеграция (1 день)

- [ ] Создать skill `/auto-dev`
- [ ] Интегрировать `hooks_route` для выбора агента
- [ ] Интегрировать `hooks_model-route` для выбора модели
- [ ] Базовый 8-фазный workflow

### Этап 2: Learning интеграция (0.5 дня)

- [ ] Добавить `hooks_pre-task` / `hooks_post-task`
- [ ] Интегрировать `memory_search` для паттернов
- [ ] Настроить `hooks_pretrain` для новых проектов

### Этап 3: Quality Gates (1 день)

- [ ] Реализовать gates с retry logic
- [ ] Интегрировать наших агентов (security-auditor, visual-qa)
- [ ] Добавить human checkpoints

### Этап 4: Memory sync (0.5 дня)

- [ ] Синхронизация claude-flow memory → Serena
- [ ] Cross-session learning
- [ ] Pattern export/import

### Этап 5: Polish (0.5 дня)

- [ ] Конфигурационные файлы
- [ ] Документация
- [ ] Тестирование на реальных проектах

---

## 7. Преимущества гибридного подхода

| Аспект | Только наш | Только claude-flow | Гибрид |
|--------|-----------|-------------------|--------|
| Q-Learning routing | ❌ | ✅ | ✅ |
| Model selection | ❌ | ✅ | ✅ |
| HNSW memory | ❌ | ✅ | ✅ |
| Security phase | ✅ | ❌ | ✅ |
| Visual QA | ✅ | ❌ | ✅ |
| Human checkpoints | ✅ | ⚠ Ad-hoc | ✅ |
| Serena cross-project | ✅ | ❌ | ✅ |
| Complexity | Low | High | Medium |

---

## 8. Риски интеграции

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| claude-flow alpha нестабилен | Средняя | Fallback к нашим агентам |
| Конфликт memory систем | Низкая | Чёткое разделение: cf=session, serena=persistent |
| Overhead от routing | Низкая | Skip для simple tasks |
| Learning noise | Средняя | Quality threshold для patterns |

---

## 9. Метрики успеха

| Метрика | Target | Как измерять |
|---------|--------|--------------|
| Routing accuracy | > 85% | hooks_explain + feedback |
| Time to PR (simple) | < 20 min | Timestamps |
| Time to PR (complex) | < 2h | Timestamps |
| Quality gate pass rate | > 90% | Gate logs |
| Learning improvement | +10%/month | Routing accuracy over time |

---

*Конец плана интеграции*
