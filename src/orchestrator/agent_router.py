"""
Agent Router

Выбирает специализированного агента для выполнения задачи.
Каждый агент имеет свой system prompt и специализацию.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Callable
import json


class AgentType(Enum):
    """Типы агентов"""
    ARCHITECT = "architect"
    CODER = "coder"
    REVIEWER = "reviewer"
    TESTER = "tester"
    DOCS = "docs"
    DEVOPS = "devops"
    DEBUGGER = "debugger"


@dataclass
class AgentConfig:
    """Конфигурация агента"""
    type: AgentType
    name: str
    description: str

    # Модели
    primary_model: str
    fallback_model: str

    # Специализации
    capabilities: List[str] = field(default_factory=list)

    # System prompt
    system_prompt: str = ""

    # Настройки генерации
    temperature: float = 0.3
    max_tokens: int = 4096

    # MCP tools доступные агенту
    allowed_tools: List[str] = field(default_factory=list)


# Системные промпты для агентов
AGENT_PROMPTS = {
    AgentType.ARCHITECT: '''Ты — Chief Software Architect с 20+ годами опыта.

## Твоя роль
Проектирование архитектуры, принятие технических решений, создание ADR.

## Принципы
1. Simplicity first (KISS)
2. Design for change
3. Оценивай риски
4. Документируй ключевые решения

## Формат ответа
При проектировании всегда включай:
- Обоснование решения
- Альтернативы и почему отклонены
- Риски и митигация
- Диаграмму (Mermaid если нужно)

## Инструменты
Используй Serena для анализа кода и памяти проекта.''',

    AgentType.CODER: '''Ты — Senior Full-Stack Developer.

## Твоя роль
Написание чистого, поддерживаемого кода согласно спецификациям.

## Принципы
1. Читай существующий код перед написанием нового
2. Следуй паттернам проекта
3. Пиши самодокументируемый код
4. DRY, SOLID
5. Обрабатывай ошибки

## Перед кодированием
1. Изучи релевантные файлы через Serena
2. Проверь memories проекта
3. Пойми существующие паттерны

## После кодирования
1. Проверь что код компилируется
2. Запусти линтер
3. Убедись в отсутствии очевидных багов

## Формат кода
- Используй типизацию
- Комментируй сложную логику
- Следуй code style проекта''',

    AgentType.REVIEWER: '''Ты — Code Review Specialist & Security Expert.

## Твоя роль
Проверка качества, безопасности и соответствия best practices.

## Чеклист
### Security
- [ ] Input validation
- [ ] Auth/authz проверки
- [ ] SQL injection, XSS защита
- [ ] Нет захардкоженных секретов

### Code Quality
- [ ] Читаемость
- [ ] Error handling
- [ ] Edge cases
- [ ] Performance

### Architecture
- [ ] Соответствует паттернам проекта
- [ ] Proper separation of concerns
- [ ] Зависимости управляемы

## Формат ответа
### 🚫 BLOCKING (обязательно исправить)
- ...

### ⚠️ WARNING (желательно исправить)
- ...

### 💡 SUGGESTION (на усмотрение)
- ...

### ✅ GOOD (что сделано хорошо)
- ...''',

    AgentType.TESTER: '''Ты — QA Engineer & Test Automation Specialist.

## Твоя роль
Написание тестов, анализ coverage, поиск edge cases.

## Стратегия тестирования
### Unit Tests
- Тестируй чистые функции
- Мокай внешние зависимости
- Покрывай edge cases
- Быстрое выполнение (<1s на тест)

### Integration Tests
- Тестируй взаимодействие компонентов
- Используй тестовые БД/сервисы

### E2E Tests
- Критические user flows
- Реальный браузер (Puppeteer)

## Targets Coverage
- Critical code: >90%
- Normal code: >70%
- Utils: >80%

## Формат отчёта
```
Tests: X passed, Y failed
Coverage: Z%
Issues found: [список]
```''',

    AgentType.DOCS: '''Ты — Technical Writer.

## Твоя роль
Написание понятной документации для разработчиков и пользователей.

## Принципы
1. Простой язык
2. Примеры для всего
3. Структурированность
4. Актуальность

## Типы документации
### README.md
- Что это
- Как установить
- Quick start
- Примеры

### API Docs
- Описание endpoint
- Request/response примеры
- Error codes
- Auth

### CHANGELOG.md
- Keep a Changelog format
- Added/Changed/Fixed/Removed

## Формат
Используй Markdown с правильным форматированием.''',

    AgentType.DEVOPS: '''Ты — DevOps Engineer & Infrastructure Specialist.

## Твоя роль
CI/CD, контейнеризация, деплой, мониторинг.

## Принципы
1. Everything as Code
2. Immutable infrastructure
3. Blue-green deployments
4. Automated rollbacks

## Stack
- Docker, Docker Compose
- GitHub Actions
- Yandex Cloud
- Nginx

## Security
- Не коммить секреты
- Используй переменные окружения
- Минимальные права''',

    AgentType.DEBUGGER: '''Ты — Debugging Specialist.

## Твоя роль
Поиск и исправление багов, анализ ошибок.

## Методология
1. Воспроизведи проблему
2. Изолируй причину
3. Сформулируй гипотезу
4. Проверь гипотезу
5. Исправь и протестируй

## Инструменты
- Логи и stack traces
- Debugger
- Print debugging
- Git bisect

## Формат отчёта
### Проблема
[описание]

### Root Cause
[причина]

### Fix
[решение]

### Prevention
[как избежать в будущем]'''
}


# Конфигурации агентов
AGENT_CONFIGS: Dict[AgentType, AgentConfig] = {
    AgentType.ARCHITECT: AgentConfig(
        type=AgentType.ARCHITECT,
        name="Architect",
        description="System design, architecture decisions, ADRs",
        primary_model="deepseek-r1:32b",
        fallback_model="llama3:70b",
        capabilities=["architecture", "planning", "adr", "tech_decisions"],
        system_prompt=AGENT_PROMPTS[AgentType.ARCHITECT],
        temperature=0.3,
        max_tokens=4096,
        allowed_tools=["serena", "memory", "filesystem"],
    ),

    AgentType.CODER: AgentConfig(
        type=AgentType.CODER,
        name="Coder",
        description="Implementation, refactoring, bug fixes",
        primary_model="qwen3-coder:30b",
        fallback_model="deepseek-coder:33b-instruct",
        capabilities=["implementation", "refactoring", "bugfix", "feature"],
        system_prompt=AGENT_PROMPTS[AgentType.CODER],
        temperature=0.2,
        max_tokens=8192,
        allowed_tools=["serena", "git", "filesystem"],
    ),

    AgentType.REVIEWER: AgentConfig(
        type=AgentType.REVIEWER,
        name="Reviewer",
        description="Code review, security audit, quality checks",
        primary_model="deepseek-r1:32b",
        fallback_model="codellama:34b",
        capabilities=["review", "security", "quality", "best_practices"],
        system_prompt=AGENT_PROMPTS[AgentType.REVIEWER],
        temperature=0.1,
        max_tokens=4096,
        allowed_tools=["serena", "git"],
    ),

    AgentType.TESTER: AgentConfig(
        type=AgentType.TESTER,
        name="Tester",
        description="Test writing, coverage analysis, QA",
        primary_model="qwen3-coder:30b",
        fallback_model="devstral",
        capabilities=["testing", "unit_tests", "integration_tests", "e2e"],
        system_prompt=AGENT_PROMPTS[AgentType.TESTER],
        temperature=0.2,
        max_tokens=6144,
        allowed_tools=["serena", "filesystem", "puppeteer"],
    ),

    AgentType.DOCS: AgentConfig(
        type=AgentType.DOCS,
        name="Docs",
        description="Documentation, README, API docs",
        primary_model="qwen3:8b",
        fallback_model="qwen3-coder:30b",
        capabilities=["documentation", "readme", "api_docs", "changelog"],
        system_prompt=AGENT_PROMPTS[AgentType.DOCS],
        temperature=0.4,
        max_tokens=4096,
        allowed_tools=["serena", "filesystem"],
    ),

    AgentType.DEVOPS: AgentConfig(
        type=AgentType.DEVOPS,
        name="DevOps",
        description="CI/CD, deployment, infrastructure",
        primary_model="qwen3-coder:30b",
        fallback_model="deepseek-r1:32b",
        capabilities=["devops", "ci_cd", "docker", "deployment"],
        system_prompt=AGENT_PROMPTS[AgentType.DEVOPS],
        temperature=0.2,
        max_tokens=4096,
        allowed_tools=["filesystem", "git"],
    ),

    AgentType.DEBUGGER: AgentConfig(
        type=AgentType.DEBUGGER,
        name="Debugger",
        description="Bug investigation, error analysis",
        primary_model="deepseek-r1:32b",
        fallback_model="qwen3-coder:30b",
        capabilities=["debugging", "error_analysis", "troubleshooting"],
        system_prompt=AGENT_PROMPTS[AgentType.DEBUGGER],
        temperature=0.2,
        max_tokens=4096,
        allowed_tools=["serena", "filesystem", "git"],
    ),
}

# Маппинг типов задач на агентов
TASK_AGENT_MAPPING = {
    "architecture": AgentType.ARCHITECT,
    "planning": AgentType.ARCHITECT,
    "design": AgentType.ARCHITECT,
    "adr": AgentType.ARCHITECT,

    "implementation": AgentType.CODER,
    "refactoring": AgentType.CODER,
    "bugfix": AgentType.CODER,
    "feature": AgentType.CODER,
    "coding": AgentType.CODER,

    "review": AgentType.REVIEWER,
    "security": AgentType.REVIEWER,
    "audit": AgentType.REVIEWER,

    "testing": AgentType.TESTER,
    "test": AgentType.TESTER,
    "coverage": AgentType.TESTER,
    "qa": AgentType.TESTER,

    "documentation": AgentType.DOCS,
    "docs": AgentType.DOCS,
    "readme": AgentType.DOCS,
    "changelog": AgentType.DOCS,

    "devops": AgentType.DEVOPS,
    "deploy": AgentType.DEVOPS,
    "ci": AgentType.DEVOPS,
    "cd": AgentType.DEVOPS,
    "docker": AgentType.DEVOPS,

    "debug": AgentType.DEBUGGER,
    "error": AgentType.DEBUGGER,
    "troubleshoot": AgentType.DEBUGGER,
}


class AgentRouter:
    """
    Роутер для выбора агента
    """

    def __init__(self):
        self.agents = AGENT_CONFIGS.copy()
        self.task_mapping = TASK_AGENT_MAPPING.copy()

    def select_agent(
        self,
        task_type: str,
        task_description: str = "",
        force_agent: Optional[AgentType] = None
    ) -> AgentConfig:
        """
        Выбрать агента для задачи

        Args:
            task_type: Тип задачи
            task_description: Описание задачи (для эвристики)
            force_agent: Принудительно выбрать агента

        Returns:
            AgentConfig
        """
        if force_agent:
            return self.agents[force_agent]

        # Прямой маппинг
        task_type_lower = task_type.lower()
        if task_type_lower in self.task_mapping:
            agent_type = self.task_mapping[task_type_lower]
            return self.agents[agent_type]

        # Эвристика по описанию
        description_lower = task_description.lower()

        keywords_to_agent = {
            AgentType.ARCHITECT: ["архитектур", "design", "проектир", "adr", "решени"],
            AgentType.CODER: ["реализ", "implement", "напис", "создай", "добав", "код"],
            AgentType.REVIEWER: ["review", "провер", "audit", "безопас", "security"],
            AgentType.TESTER: ["тест", "test", "coverage", "qa", "проверк"],
            AgentType.DOCS: ["документ", "readme", "changelog", "doc"],
            AgentType.DEVOPS: ["deploy", "ci/cd", "docker", "деплой"],
            AgentType.DEBUGGER: ["debug", "ошибк", "error", "баг", "bug", "исправ"],
        }

        for agent_type, keywords in keywords_to_agent.items():
            if any(kw in description_lower for kw in keywords):
                return self.agents[agent_type]

        # По умолчанию — Coder
        return self.agents[AgentType.CODER]

    def get_agent(self, agent_type: AgentType) -> AgentConfig:
        """Получить конфигурацию агента по типу"""
        return self.agents[agent_type]

    def get_all_agents(self) -> List[AgentConfig]:
        """Получить все агенты"""
        return list(self.agents.values())

    def get_agent_for_retry(
        self,
        failed_agent: AgentType,
        error_type: str = ""
    ) -> AgentConfig:
        """
        Выбрать агента для повторной попытки

        При неудаче одного агента может помочь другой
        """
        # Если Coder не справился — попробуем Debugger
        if failed_agent == AgentType.CODER:
            if "error" in error_type.lower() or "bug" in error_type.lower():
                return self.agents[AgentType.DEBUGGER]

        # Если Tester не справился — попробуем Coder исправить
        if failed_agent == AgentType.TESTER:
            return self.agents[AgentType.CODER]

        # По умолчанию — Architect для анализа
        return self.agents[AgentType.ARCHITECT]

    def build_agent_prompt(
        self,
        agent: AgentConfig,
        task_context: str,
        project_context: str = ""
    ) -> str:
        """
        Построить полный промпт для агента

        Args:
            agent: Конфигурация агента
            task_context: Контекст задачи
            project_context: Контекст проекта (из RAG)

        Returns:
            Полный промпт
        """
        parts = [agent.system_prompt]

        if project_context:
            parts.append(f"\n## Контекст проекта\n{project_context}")

        parts.append(f"\n## Задача\n{task_context}")

        return "\n".join(parts)


# CLI для тестирования
if __name__ == "__main__":
    router = AgentRouter()

    print("🤖 Agent Router")
    print("=" * 50)

    print("\n📋 Available Agents:")
    for agent in router.get_all_agents():
        print(f"  {agent.type.value:12} | {agent.primary_model:25} | {agent.capabilities[:3]}")

    print("\n🔍 Task → Agent Mapping:")
    test_tasks = [
        ("architecture", "Спроектировать систему аутентификации"),
        ("implementation", "Написать API endpoint"),
        ("review", "Проверить код на безопасность"),
        ("testing", "Написать unit тесты"),
        ("documentation", "Обновить README"),
    ]

    for task_type, description in test_tasks:
        agent = router.select_agent(task_type, description)
        print(f"  {task_type:15} → {agent.name:12} ({agent.primary_model})")
