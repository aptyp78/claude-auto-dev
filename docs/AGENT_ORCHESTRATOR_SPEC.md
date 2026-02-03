# Agent Orchestrator — Полная спецификация

> **Версия:** 1.0.0-draft
> **Автор:** Claude Code + Arthur Ocheretny
> **Дата:** 2026-02-03
> **Статус:** Проектирование

---

## 1. Обзор системы

### 1.1 Цель

Создать автономную мультиагентную систему для разработки, которая:
- Принимает описание задачи на естественном языке
- Проводит диалог для уточнения требований
- Автоматически выполняет полный цикл разработки
- Гарантирует качество через Quality Gates
- Доводит код до готовности к деплою

### 1.2 Принципы

| Принцип | Описание |
|---------|----------|
| **Автономность** | Минимальное участие человека в рутинных операциях |
| **Качество** | Код не продвигается без прохождения проверок |
| **Прозрачность** | Каждое решение логируется и объяснимо |
| **Восстанавливаемость** | Сбои автоматически исправляются или эскалируются |
| **Универсальность** | Работает с любым стеком (Python, JS, Go, etc.) |

### 1.3 Компоненты верхнего уровня

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AGENT ORCHESTRATOR                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │   ROUTER    │  │    STATE    │  │   WORKER    │  │   QUALITY   │ │
│  │             │  │   MANAGER   │  │    POOL     │  │    GATES    │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │
│                                                                       │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐ │
│  │   RETRY     │  │   HUMAN     │  │   MEMORY    │  │   DEPLOY    │ │
│  │   ENGINE    │  │  INTERFACE  │  │   LAYER     │  │   ENGINE    │ │
│  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘ │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. Архитектура компонентов

### 2.1 Router (Маршрутизатор)

**Назначение:** Определение типа задачи и выбор workflow.

```yaml
router:
  inputs:
    - user_task_description: string
    - project_context: ProjectContext

  outputs:
    - workflow_type: enum[feature, bugfix, refactor, docs, test]
    - phases_to_run: Phase[]
    - estimated_complexity: enum[simple, medium, complex]

  logic:
    - Анализ ключевых слов в описании
    - Определение затрагиваемых компонентов
    - Выбор подходящего workflow
```

**Типы workflow:**

| Тип | Фазы | Пример задачи |
|-----|------|---------------|
| `feature` | Все 8 фаз | "Добавить авторизацию через OAuth" |
| `bugfix` | Discover → Build → Test → Review → Deploy | "Исправить ошибку в парсере" |
| `refactor` | Discover → Plan → Build → Test → Review | "Отрефакторить модуль X" |
| `docs` | Discover → Build → Review → Deploy | "Обновить документацию API" |
| `test` | Discover → Build → Test | "Добавить тесты для модуля Y" |

### 2.2 State Manager (Менеджер состояния)

**Назначение:** Отслеживание прогресса и хранение контекста.

```typescript
interface OrchestratorState {
  // Идентификация
  session_id: string;
  project_path: string;
  started_at: timestamp;

  // Задача
  task: {
    description: string;
    type: WorkflowType;
    requirements: Requirement[];
  };

  // Прогресс
  current_phase: PhaseId;
  phases: {
    [phase_id: string]: {
      status: 'pending' | 'running' | 'passed' | 'failed' | 'skipped';
      started_at?: timestamp;
      completed_at?: timestamp;
      attempts: number;
      outputs: any;
      errors: Error[];
    }
  };

  // Задачи
  tasks: Task[];  // Интеграция с Task tools

  // Артефакты
  artifacts: {
    plan?: PlanDocument;
    changed_files: string[];
    test_results?: TestResults;
    review_comments: ReviewComment[];
    security_findings: SecurityFinding[];
  };

  // Human interactions
  approvals: {
    plan_approved: boolean;
    deploy_approved: boolean;
  };
}
```

**Персистентность:**

```
SESSION STORAGE (Task tools)     PERSISTENT STORAGE (Serena)
┌─────────────────────────┐     ┌─────────────────────────┐
│ • Текущий state         │     │ • История сессий        │
│ • Task list             │────▶│ • Паттерны проекта      │
│ • Промежуточные данные  │     │ • Накопленные знания    │
└─────────────────────────┘     └─────────────────────────┘
```

### 2.3 Worker Pool (Пул воркеров)

**Назначение:** Управление специализированными агентами.

```yaml
worker_pool:
  agents:
    # Discovery
    explore:
      type: Explore
      model: haiku  # Быстрый для поиска

    # Planning
    plan:
      type: Plan
      model: opus

    chief_architect:
      type: chief-architect
      model: opus

    # Development
    backend:
      type: backend-architect
      model: opus

    frontend:
      type: frontend-developer
      model: opus

    database:
      type: database-architect
      model: opus

    python_pro:
      type: python-pro
      model: opus

    # Testing
    test_automator:
      type: test-automator
      model: sonnet

    debugger:
      type: debugger
      model: opus

    # Review
    code_reviewer:
      type: code-reviewer
      model: opus

    silent_failure_hunter:
      type: silent-failure-hunter
      model: sonnet

    type_analyzer:
      type: type-design-analyzer
      model: sonnet

    # Security
    security_auditor:
      type: security-auditor
      model: opus

    # Deployment
    deployment_engineer:
      type: deployment-engineer
      model: sonnet

  execution_modes:
    parallel:
      max_concurrent: 3
      strategy: "independent_tasks"

    sequential:
      wait_for_completion: true
      pass_context: true
```

### 2.4 Quality Gates (Контрольные точки)

**Назначение:** Блокировка перехода при несоответствии критериям.

```yaml
quality_gates:

  after_discover:
    name: "Discovery Complete"
    criteria:
      - project_structure_understood: true
      - dependencies_identified: true
      - patterns_documented: true
    on_fail: retry_with_deeper_exploration
    max_retries: 2

  after_plan:
    name: "Plan Approved"
    criteria:
      - plan_document_exists: true
      - tasks_created: true
      - human_approval: required
    on_fail: revise_plan
    human_checkpoint: true

  after_build:
    name: "Implementation Complete"
    criteria:
      - all_tasks_completed: true
      - no_syntax_errors: true
      - code_compiles: true
    on_fail: fix_and_retry
    max_retries: 3

  after_test:
    name: "Tests Passing"
    criteria:
      - all_tests_pass: true
      - coverage_threshold: 80%
      - no_regressions: true
    on_fail: debug_and_fix
    max_retries: 5

  after_review:
    name: "Review Passed"
    criteria:
      - no_critical_issues: true
      - no_high_issues: true
      - medium_issues_acknowledged: true
    on_fail: address_comments
    max_retries: 3

  after_security:
    name: "Security Cleared"
    criteria:
      - no_critical_vulnerabilities: true
      - no_high_vulnerabilities: true
      - secrets_not_exposed: true
    on_fail: fix_vulnerabilities
    human_checkpoint_if_critical: true
    max_retries: 3

  after_visual_qa:
    name: "Visual QA Passed"
    criteria:
      - no_visual_regressions: true
      - accessibility_passed: true
    on_fail: fix_ui_issues
    max_retries: 2
    condition: has_frontend_changes

  before_deploy:
    name: "Ready for Deploy"
    criteria:
      - all_gates_passed: true
      - human_approval: required
    human_checkpoint: true
```

### 2.5 Retry Engine (Движок повторов)

**Назначение:** Автоматическое исправление и повторная попытка.

```yaml
retry_engine:
  strategies:

    debug_and_fix:
      description: "Для падающих тестов"
      steps:
        1: "Запустить debugger агента для анализа"
        2: "Получить диагноз и план исправления"
        3: "Применить исправления"
        4: "Перезапустить тесты"
      escalate_after: 5 attempts

    address_comments:
      description: "Для замечаний code review"
      steps:
        1: "Собрать все замечания"
        2: "Приоритизировать по критичности"
        3: "Исправить critical и high"
        4: "Перезапустить review"
      escalate_after: 3 attempts

    fix_vulnerabilities:
      description: "Для security issues"
      steps:
        1: "Классифицировать уязвимости"
        2: "Применить рекомендованные исправления"
        3: "Перезапустить security scan"
      escalate_to_human: "if critical remains"

    revise_plan:
      description: "Если план отклонён"
      steps:
        1: "Получить feedback от пользователя"
        2: "Переработать план с учётом замечаний"
        3: "Представить обновлённый план"
      always_involves_human: true

  escalation:
    trigger: "max_retries_exceeded OR critical_issue"
    action: "Pause and notify human with full context"
    data_provided:
      - all_attempts_log
      - error_analysis
      - recommended_actions
```

### 2.6 Human Interface (Интерфейс с человеком)

**Назначение:** Взаимодействие с пользователем в критические моменты.

```yaml
human_interface:

  checkpoints:
    plan_approval:
      trigger: "after_plan phase"
      display:
        - plan_summary
        - task_list
        - estimated_scope
      options:
        - approve: "Продолжить реализацию"
        - modify: "Внести изменения в план"
        - reject: "Отменить и переделать"

    deploy_approval:
      trigger: "before_deploy phase"
      display:
        - all_changes_summary
        - test_results
        - review_summary
        - security_report
      options:
        - deploy: "Задеплоить"
        - pr_only: "Создать PR без деплоя"
        - hold: "Отложить"

  notifications:
    on_phase_complete:
      format: "short_summary"

    on_error:
      format: "detailed_with_context"

    on_escalation:
      format: "full_report_with_options"

  input_collection:
    clarification:
      method: AskUserQuestion
      max_questions: 4

    feedback:
      method: "free_text OR structured"
```

### 2.7 Memory Layer (Слой памяти)

**Назначение:** Интеграция с Serena для долгосрочной памяти.

```yaml
memory_layer:

  write_triggers:
    - session_complete: "orchestrator_session_{date}"
    - significant_decision: "decision_{topic}_{date}"
    - pattern_discovered: "pattern_{name}"
    - error_resolved: "fix_{error_type}_{date}"

  read_triggers:
    - session_start: "load relevant project memories"
    - planning_phase: "load past decisions and patterns"
    - error_encountered: "search for similar past fixes"

  memory_types:
    project_knowledge:
      - architecture_decisions
      - coding_patterns
      - common_issues

    session_history:
      - task_descriptions
      - outcomes
      - lessons_learned

    error_database:
      - error_signatures
      - successful_fixes
      - escalation_history
```

### 2.8 Deploy Engine (Движок деплоя)

**Назначение:** Финальная стадия — создание PR или деплой.

```yaml
deploy_engine:

  modes:
    pr_only:
      steps:
        1: "Создать feature branch"
        2: "Commit all changes"
        3: "Push to remote"
        4: "Create PR with full description"
      output: "PR URL"

    staging_deploy:
      steps:
        1: "Create PR"
        2: "Wait for CI"
        3: "Deploy to staging"
        4: "Run smoke tests"
      output: "Staging URL"

    production_deploy:
      steps:
        1: "Merge PR"
        2: "Wait for CI/CD"
        3: "Monitor deployment"
        4: "Verify health"
      output: "Production URL"
      requires: "explicit human approval"

  integrations:
    github:
      via: "gh CLI"
      capabilities: [pr_create, pr_merge, actions_status]

    custom_ci:
      via: "Bash hooks"
      capabilities: [trigger_build, check_status]
```

---

## 3. Детальное описание фаз

### 3.1 Phase 1: DISCOVER

```yaml
phase_discover:
  name: "Discovery"
  purpose: "Понять кодовую базу и контекст задачи"

  inputs:
    - task_description: string
    - project_path: string

  agents:
    - type: Explore
      count: 1-3 (based on task complexity)
      focus_areas:
        - "Структура проекта"
        - "Существующие паттерны"
        - "Связанный код"

  activities:
    1: "Анализ структуры директорий"
    2: "Поиск связанных файлов"
    3: "Изучение существующих паттернов"
    4: "Идентификация зависимостей"
    5: "Документирование findings"

  outputs:
    - project_structure: DirectoryTree
    - related_files: string[]
    - patterns: Pattern[]
    - dependencies: Dependency[]
    - tech_stack: TechStack

  duration_estimate: "2-10 minutes"

  quality_gate:
    name: "Discovery Complete"
    pass_criteria:
      - found_relevant_files: "> 0"
      - tech_stack_identified: true
```

### 3.2 Phase 2: PLAN

```yaml
phase_plan:
  name: "Planning"
  purpose: "Создать детальный план реализации"

  inputs:
    - discovery_outputs: DiscoveryResult
    - task_description: string

  agents:
    primary:
      - type: Plan
        focus: "Общая архитектура решения"

    optional:
      - type: chief-architect
        condition: "complexity >= medium"
        focus: "Архитектурные решения"

      - type: /ultrathink
        condition: "complexity == complex"
        focus: "Глубокий анализ подходов"

  activities:
    1: "Декомпозиция задачи на подзадачи"
    2: "Определение порядка выполнения"
    3: "Идентификация рисков"
    4: "Выбор технических решений"
    5: "Создание Task list"

  outputs:
    - plan_document: PlanDocument
    - tasks: Task[]
    - risks: Risk[]
    - decisions: Decision[]

  human_checkpoint:
    required: true
    display: "План реализации для одобрения"
    options: [approve, modify, reject]

  duration_estimate: "5-15 minutes"
```

### 3.3 Phase 3: BUILD

```yaml
phase_build:
  name: "Implementation"
  purpose: "Реализовать код согласно плану"

  inputs:
    - approved_plan: PlanDocument
    - tasks: Task[]

  agents:
    # Выбор агентов на основе tech stack
    selectors:
      python:
        - python-pro
        - fastapi-pro (if FastAPI)
        - django-pro (if Django)

      javascript:
        - frontend-developer
        - web-dev

      backend:
        - backend-architect

      database:
        - database-architect
        - sql-pro

  execution:
    mode: "parallel where independent"
    coordination:
      - "Общие файлы — sequential"
      - "Независимые модули — parallel"

  activities:
    1: "Создание/модификация файлов"
    2: "Написание кода"
    3: "Обновление импортов и зависимостей"
    4: "Базовая валидация (syntax, imports)"

  task_flow:
    for_each_task:
      1: "TaskUpdate status=in_progress"
      2: "Execute implementation"
      3: "Validate basic correctness"
      4: "TaskUpdate status=completed"

  outputs:
    - changed_files: string[]
    - new_files: string[]
    - implementation_notes: string[]

  quality_gate:
    name: "Implementation Complete"
    criteria:
      - all_tasks_completed: true
      - no_syntax_errors: true
      - all_imports_resolve: true
```

### 3.4 Phase 4: TEST

```yaml
phase_test:
  name: "Testing"
  purpose: "Написать и запустить тесты"

  inputs:
    - changed_files: string[]
    - implementation_notes: string[]

  agents:
    - type: test-automator
      role: "Написание тестов"

    - type: debugger
      role: "Исправление падающих тестов"
      trigger: "on test failure"

  activities:
    1: "Анализ что нужно тестировать"
    2: "Написание unit тестов"
    3: "Написание integration тестов (if needed)"
    4: "Запуск тестов"
    5: "Анализ failures"
    6: "Исправление кода или тестов"

  test_strategy:
    unit_tests:
      coverage_target: 80%
      frameworks:
        python: pytest
        javascript: jest/vitest

    integration_tests:
      condition: "if API or DB changes"

  retry_on_failure:
    strategy: debug_and_fix
    max_attempts: 5

  outputs:
    - test_files: string[]
    - test_results: TestResults
    - coverage_report: CoverageReport

  quality_gate:
    name: "Tests Passing"
    criteria:
      - all_tests_pass: true
      - coverage: ">= 80%"
      - no_regressions: true
```

### 3.5 Phase 5: REVIEW

```yaml
phase_review:
  name: "Code Review"
  purpose: "Проверить качество кода"

  inputs:
    - changed_files: string[]
    - test_results: TestResults

  agents:
    sequence:  # Последовательно, каждый может найти новые проблемы
      1:
        type: code-reviewer
        focus: "Общее качество, паттерны, стиль"

      2:
        type: silent-failure-hunter
        focus: "Ошибки обработки, silent failures"

      3:
        type: type-design-analyzer
        focus: "Качество типов и инвариантов"
        condition: "if TypeScript or typed Python"

  review_criteria:
    critical:  # Блокирующие
      - security_issues
      - data_loss_risk
      - breaking_changes_undocumented

    high:  # Требуют исправления
      - error_handling_missing
      - performance_issues
      - test_gaps

    medium:  # Желательно исправить
      - code_style
      - documentation_missing
      - naming_improvements

    low:  # На усмотрение
      - minor_suggestions

  activities:
    1: "Запуск code-reviewer"
    2: "Сбор замечаний"
    3: "Запуск silent-failure-hunter"
    4: "Добавление замечаний"
    5: "Приоритизация issues"
    6: "Исправление critical/high"
    7: "Перезапуск review при необходимости"

  retry_on_failure:
    strategy: address_comments
    max_attempts: 3

  outputs:
    - review_report: ReviewReport
    - issues_found: Issue[]
    - issues_fixed: Issue[]

  quality_gate:
    name: "Review Passed"
    criteria:
      - critical_issues: 0
      - high_issues: 0
```

### 3.6 Phase 6: SECURITY

```yaml
phase_security:
  name: "Security Audit"
  purpose: "Проверить безопасность изменений"

  inputs:
    - changed_files: string[]
    - project_context: ProjectContext

  agents:
    - type: security-auditor
      full_scan: false  # Только изменённые файлы

  checks:
    owasp_top_10:
      - injection
      - broken_auth
      - sensitive_data_exposure
      - xxe
      - broken_access_control
      - security_misconfiguration
      - xss
      - insecure_deserialization
      - vulnerable_components
      - insufficient_logging

    secrets_detection:
      - api_keys
      - passwords
      - tokens
      - certificates

    dependency_audit:
      - known_vulnerabilities
      - outdated_packages

  severity_levels:
    critical:
      action: "block + notify human"
      examples: ["SQL injection", "exposed secrets"]

    high:
      action: "block + auto-fix if possible"
      examples: ["XSS", "weak crypto"]

    medium:
      action: "warn + suggest fix"

    low:
      action: "log for info"

  outputs:
    - security_report: SecurityReport
    - vulnerabilities: Vulnerability[]
    - remediation_applied: Remediation[]

  quality_gate:
    name: "Security Cleared"
    criteria:
      - critical_vulnerabilities: 0
      - high_vulnerabilities: 0
      - secrets_exposed: false
```

### 3.7 Phase 7: VISUAL QA (Conditional)

```yaml
phase_visual_qa:
  name: "Visual QA"
  purpose: "Проверить UI изменения"

  condition: "has_frontend_changes"

  inputs:
    - changed_files: string[]  # Filtered to UI files
    - baseline_screenshots: Screenshot[]  # If available

  agents:
    - type: visual-qa MCP

  checks:
    visual_regression:
      - compare_to_baseline
      - highlight_differences
      - threshold: "5% pixel diff"

    accessibility:
      - wcag_compliance
      - color_contrast
      - keyboard_navigation

    responsive:
      - mobile_breakpoints
      - tablet_breakpoints
      - desktop_breakpoints

  activities:
    1: "Запуск приложения (dev server)"
    2: "Создание скриншотов"
    3: "Сравнение с baseline"
    4: "Accessibility audit"
    5: "Генерация отчёта"

  outputs:
    - visual_report: VisualReport
    - screenshots: Screenshot[]
    - accessibility_issues: A11yIssue[]

  quality_gate:
    name: "Visual QA Passed"
    criteria:
      - visual_regressions: 0
      - critical_a11y_issues: 0
```

### 3.8 Phase 8: DEPLOY

```yaml
phase_deploy:
  name: "Deployment"
  purpose: "Создать PR или задеплоить"

  inputs:
    - all_phase_outputs: PhaseOutputs
    - deploy_mode: DeployMode

  agents:
    - type: deployment-engineer

  human_checkpoint:
    required: true
    display:
      - changes_summary
      - test_results
      - review_summary
      - security_report
    options:
      - deploy: "Задеплоить в production"
      - staging: "Задеплоить в staging"
      - pr_only: "Только создать PR"
      - hold: "Отложить"

  deploy_modes:
    pr_only:
      steps:
        1: "git checkout -b feature/..."
        2: "git add changed_files"
        3: "git commit with detailed message"
        4: "git push -u origin branch"
        5: "gh pr create with full description"

    staging:
      steps:
        1: "Create PR"
        2: "Wait for CI checks"
        3: "Merge to staging branch"
        4: "Monitor staging deployment"
        5: "Run smoke tests"

    production:
      steps:
        1: "Merge PR to main"
        2: "Wait for CI/CD pipeline"
        3: "Monitor production deployment"
        4: "Verify health checks"
        5: "Notify completion"

  outputs:
    - deployment_result: DeploymentResult
    - pr_url: string  # If PR created
    - deployment_url: string  # If deployed

  post_deploy:
    - write_session_to_serena_memory
    - update_changelog  # If significant
    - notify_user_completion
```

---

## 4. Формат файла Skill

### 4.1 Структура `/auto-dev` skill

Расположение: `~/.claude/commands/auto-dev.md`

```markdown
# Auto-Dev Orchestrator

Запуск: `/auto-dev <описание задачи>`

## Workflow

### Инициализация

1. Проанализировать описание задачи
2. Определить тип workflow (feature/bugfix/refactor/docs/test)
3. Создать session state
4. Загрузить релевантные Serena memories

### Фаза 1: Discovery

Запустить Explore агентов для понимания кодовой базы:
- Структура проекта
- Связанные файлы
- Существующие паттерны

**Gate:** Достаточно информации для планирования

### Фаза 2: Planning

Запустить Plan агента для создания плана:
- Декомпозиция на задачи
- Определение зависимостей
- Идентификация рисков

**Human Checkpoint:** Одобрение плана

### Фаза 3: Build

Запустить специализированных агентов:
- backend-architect / frontend-developer / etc.
- Параллельно для независимых задач

**Gate:** Все задачи выполнены, код компилируется

### Фаза 4: Test

Запустить test-automator:
- Написание тестов
- Запуск тестов
- При failures — debugger для исправления

**Gate:** Все тесты проходят, coverage >= 80%

### Фаза 5: Review

Последовательно запустить:
1. code-reviewer
2. silent-failure-hunter
3. type-design-analyzer (если typed)

**Gate:** Нет critical/high issues

### Фаза 6: Security

Запустить security-auditor:
- OWASP checks
- Secrets detection
- Dependency audit

**Gate:** Нет critical/high vulnerabilities

### Фаза 7: Visual QA (если frontend)

Запустить visual-qa:
- Скриншоты
- Сравнение с baseline
- Accessibility

**Gate:** Нет visual regressions

### Фаза 8: Deploy

**Human Checkpoint:** Выбор действия

Опции:
- Создать PR
- Deploy to staging
- Deploy to production
- Отложить

### Завершение

- Сохранить сессию в Serena memory
- Показать итоговый отчёт
```

### 4.2 Интеграция с существующими skills

```yaml
skill_integrations:
  /ultrathink:
    use_in: planning_phase
    when: "complexity == complex"

  /audit:
    use_in: security_phase
    as: "additional deep scan"

  /test-fix:
    use_in: test_phase
    as: "retry strategy"

  /code-review:
    use_in: review_phase
    as: "primary reviewer"

  /commit-push-pr:
    use_in: deploy_phase
    as: "git operations"
```

---

## 5. Конфигурация

### 5.1 Глобальная конфигурация

Файл: `~/.claude/orchestrator.yaml`

```yaml
orchestrator:
  version: "1.0"

  defaults:
    workflow: feature
    coverage_threshold: 80
    max_retries: 3
    parallel_agents: 3

  quality_gates:
    strict_mode: true  # Не пропускать при failures

  human_checkpoints:
    plan_approval: required
    deploy_approval: required
    security_escalation: auto  # Эскалация при critical

  memory:
    auto_save_sessions: true
    memory_prefix: "orchestrator_"

  notifications:
    on_phase_complete: brief
    on_error: detailed
    on_complete: full_report
```

### 5.2 Проектная конфигурация

Файл: `<project>/.claude/orchestrator.yaml`

```yaml
# Переопределения для конкретного проекта
orchestrator:
  tech_stack:
    language: python
    framework: fastapi
    database: postgresql

  coverage_threshold: 90  # Выше для этого проекта

  skip_phases:
    - visual_qa  # Нет frontend

  custom_checks:
    - name: "mypy type check"
      command: "mypy src/"
      phase: build
```

---

## 6. План реализации

### Этап 1: MVP (1-2 дня)

**Цель:** Базовый working prototype

- [ ] Создать skill `/auto-dev`
- [ ] Реализовать базовый workflow (discover → plan → build)
- [ ] Добавить простой state management через Task tools
- [ ] Интегрировать 3-4 основных агента

**Результат:** Можно запустить `/auto-dev "задача"` и получить код

### Этап 2: Quality Gates (1 день)

**Цель:** Добавить проверки качества

- [ ] Интегрировать test-automator
- [ ] Интегрировать code-reviewer
- [ ] Добавить quality gates между фазами
- [ ] Реализовать базовый retry logic

**Результат:** Код проходит тесты и review перед завершением

### Этап 3: Security & Full Review (1 день)

**Цель:** Полный набор проверок

- [ ] Интегрировать security-auditor
- [ ] Добавить silent-failure-hunter
- [ ] Интегрировать visual-qa (conditional)
- [ ] Реализовать human checkpoints

**Результат:** Полный pipeline проверок

### Этап 4: Memory & Persistence (0.5 дня)

**Цель:** Долгосрочная память

- [ ] Интеграция с Serena memories
- [ ] Автосохранение сессий
- [ ] Загрузка контекста при старте

**Результат:** Система учится на прошлых сессиях

### Этап 5: Deploy Integration (0.5 дня)

**Цель:** Автоматизация деплоя

- [ ] Интеграция с git/github
- [ ] PR creation с полным описанием
- [ ] Optional staging/production deploy

**Результат:** Полный цикл до деплоя

### Этап 6: Polish & Config (0.5 дня)

**Цель:** Удобство использования

- [ ] Конфигурационные файлы
- [ ] Красивые отчёты
- [ ] Документация
- [ ] Тестирование на реальных проектах

**Результат:** Production-ready система

---

## 7. Риски и митигации

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Агенты конфликтуют при параллельной работе | Средняя | Высокое | Чёткое разделение файлов, sequential для shared resources |
| Бесконечные retry loops | Низкая | Высокое | Hard limit на retries, эскалация к человеку |
| Потеря контекста между фазами | Средняя | Среднее | Явная передача outputs, state management |
| Слишком долгое выполнение | Средняя | Среднее | Timeouts, progress notifications, parallel execution |
| Ложные срабатывания security | Высокая | Низкое | Настраиваемые thresholds, whitelist |

---

## 8. Метрики успеха

| Метрика | Target | Как измерять |
|---------|--------|--------------|
| Время от задачи до PR | < 30 min (simple), < 2h (complex) | Timestamps в state |
| Успешность с первой попытки | > 70% | Счётчик retries |
| Quality gate pass rate | > 90% | Логи gates |
| Удовлетворённость пользователя | > 4/5 | Feedback после сессии |

---

## Приложение A: Глоссарий

| Термин | Определение |
|--------|-------------|
| **Phase** | Этап workflow (discover, plan, build, etc.) |
| **Quality Gate** | Контрольная точка с критериями прохождения |
| **Worker** | Специализированный агент для конкретной задачи |
| **Retry Strategy** | Алгоритм повторной попытки при failure |
| **Human Checkpoint** | Точка, требующая одобрения человека |
| **State** | Текущее состояние выполнения workflow |

---

## Приложение B: Примеры использования

### Пример 1: Добавление новой функции

```
/auto-dev "Добавить endpoint для экспорта отчётов в PDF"

[DISCOVER] Анализ проекта...
  ✓ FastAPI проект
  ✓ Найден модуль reports/
  ✓ Существующие endpoints в api/v1/

[PLAN] Создание плана...
  1. Добавить зависимость weasyprint
  2. Создать reports/pdf_generator.py
  3. Добавить endpoint GET /api/v1/reports/{id}/pdf
  4. Написать тесты

  Одобрить план? [Да / Изменить / Отмена]
  > Да

[BUILD] Реализация...
  ✓ Задача 1/4: weasyprint добавлен
  ✓ Задача 2/4: pdf_generator.py создан
  ✓ Задача 3/4: endpoint добавлен
  ✓ Задача 4/4: тесты написаны

[TEST] Тестирование...
  ✓ 5/5 тестов проходят
  ✓ Coverage: 87%

[REVIEW] Code review...
  ✓ code-reviewer: OK
  ✓ silent-failure-hunter: OK

[SECURITY] Security audit...
  ✓ Нет уязвимостей

[DEPLOY] Что делаем?
  1. Создать PR
  2. Deploy to staging
  3. Отложить
  > 1

✓ PR создан: https://github.com/user/repo/pull/42
```

### Пример 2: Исправление бага

```
/auto-dev "Исправить: пользователи не могут войти после смены пароля"

[DISCOVER] Анализ проблемы...
  ✓ Найден auth/service.py
  ✓ Найден тест test_auth.py (падает!)

[PLAN] Анализ...
  Тип: bugfix
  Причина: токен не инвалидируется при смене пароля
  Исправление: добавить invalidate_tokens() в change_password()

[BUILD] Исправление...
  ✓ auth/service.py обновлён

[TEST] Тестирование...
  ✗ 1 тест падает

  [RETRY] debugger анализирует...
  ✓ Исправлено: нужен await
  ✓ 8/8 тестов проходят

[REVIEW + SECURITY] OK

[DEPLOY] PR создан: #43
```

---

*Конец спецификации*
