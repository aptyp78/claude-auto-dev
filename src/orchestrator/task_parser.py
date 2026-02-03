"""
Task Parser & Planner

Разбирает пользовательский запрос на подзадачи и строит граф зависимостей.
Использует быструю модель (qwen3:8b) для декомпозиции.
"""

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Optional, Set
from datetime import datetime
import httpx


class TaskType(Enum):
    """Типы задач"""
    ARCHITECTURE = "architecture"      # Проектирование, ADR
    IMPLEMENTATION = "implementation"  # Написание кода
    REFACTORING = "refactoring"       # Рефакторинг
    BUGFIX = "bugfix"                 # Исправление багов
    TESTING = "testing"               # Написание тестов
    REVIEW = "review"                 # Code review
    DOCUMENTATION = "documentation"   # Документация
    DEVOPS = "devops"                 # CI/CD, деплой
    RESEARCH = "research"             # Исследование кодовой базы


class TaskPriority(Enum):
    """Приоритеты задач"""
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


class TaskStatus(Enum):
    """Статусы задач"""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class Task:
    """Представление одной задачи"""
    id: str
    title: str
    description: str
    type: TaskType
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING

    # Зависимости
    depends_on: List[str] = field(default_factory=list)
    blocks: List[str] = field(default_factory=list)

    # Контекст
    files_to_read: List[str] = field(default_factory=list)
    files_to_modify: List[str] = field(default_factory=list)
    estimated_tokens: int = 0

    # Результат
    result: Optional[str] = None
    error: Optional[str] = None

    # Метаданные
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def is_ready(self, completed_tasks: Set[str]) -> bool:
        """Проверяет, готова ли задача к выполнению"""
        return all(dep in completed_tasks for dep in self.depends_on)

    def to_dict(self) -> dict:
        """Конвертация в словарь"""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "type": self.type.value,
            "priority": self.priority.value,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "blocks": self.blocks,
            "files_to_read": self.files_to_read,
            "files_to_modify": self.files_to_modify,
        }


@dataclass
class TaskGraph:
    """Граф задач с зависимостями"""
    tasks: Dict[str, Task] = field(default_factory=dict)
    root_task_id: Optional[str] = None

    def add_task(self, task: Task) -> None:
        """Добавить задачу в граф"""
        self.tasks[task.id] = task

        # Обновить обратные связи
        for dep_id in task.depends_on:
            if dep_id in self.tasks:
                if task.id not in self.tasks[dep_id].blocks:
                    self.tasks[dep_id].blocks.append(task.id)

    def get_ready_tasks(self, completed: Set[str]) -> List[Task]:
        """Получить задачи, готовые к выполнению"""
        ready = []
        for task in self.tasks.values():
            if task.status == TaskStatus.PENDING and task.is_ready(completed):
                ready.append(task)

        # Сортировка по приоритету
        ready.sort(key=lambda t: t.priority.value)
        return ready

    def get_execution_order(self) -> List[str]:
        """Топологическая сортировка для порядка выполнения"""
        visited = set()
        order = []

        def dfs(task_id: str):
            if task_id in visited:
                return
            visited.add(task_id)

            task = self.tasks.get(task_id)
            if task:
                for dep_id in task.depends_on:
                    dfs(dep_id)
                order.append(task_id)

        for task_id in self.tasks:
            dfs(task_id)

        return order

    def to_mermaid(self) -> str:
        """Генерация Mermaid диаграммы"""
        lines = ["graph TD"]

        for task in self.tasks.values():
            # Узел
            status_emoji = {
                TaskStatus.PENDING: "⏳",
                TaskStatus.IN_PROGRESS: "🔄",
                TaskStatus.COMPLETED: "✅",
                TaskStatus.FAILED: "❌",
                TaskStatus.BLOCKED: "🚫",
            }
            emoji = status_emoji.get(task.status, "")
            lines.append(f'    {task.id}["{emoji} {task.title}"]')

            # Связи
            for dep_id in task.depends_on:
                lines.append(f'    {dep_id} --> {task.id}')

        return "\n".join(lines)


class TaskParser:
    """
    Парсер задач с использованием LLM для декомпозиции
    """

    DECOMPOSITION_PROMPT = '''Ты — эксперт по декомпозиции задач разработки.

Разбей следующую задачу на подзадачи. Для каждой подзадачи укажи:
- id: уникальный идентификатор (task_1, task_2, ...)
- title: короткое название
- description: подробное описание что нужно сделать
- type: тип задачи (architecture, implementation, refactoring, bugfix, testing, review, documentation, devops, research)
- priority: приоритет (1=critical, 2=high, 3=medium, 4=low)
- depends_on: список id задач, от которых зависит эта задача

ЗАДАЧА: {task_description}

КОНТЕКСТ ПРОЕКТА:
{project_context}

Ответь в формате JSON:
```json
{{
  "workflow_type": "feature|bugfix|refactor|docs|test",
  "summary": "краткое описание плана",
  "tasks": [
    {{
      "id": "task_1",
      "title": "...",
      "description": "...",
      "type": "...",
      "priority": 2,
      "depends_on": []
    }}
  ]
}}
```

Важно:
- Первая задача обычно research или architecture
- Implementation зависит от architecture
- Testing зависит от implementation
- Review зависит от implementation
- Documentation может быть параллельно'''

    CLASSIFICATION_PROMPT = '''Классифицируй задачу разработки.

ЗАДАЧА: {task_description}

Определи:
1. workflow_type: feature|bugfix|refactor|docs|test
2. complexity: simple|medium|complex
3. estimated_tasks: примерное количество подзадач (1-10)
4. needs_architecture: true/false — нужен ли этап проектирования
5. needs_testing: true/false — нужны ли тесты
6. primary_language: основной язык (python/javascript/go/etc)

Ответь в JSON:
```json
{{
  "workflow_type": "feature",
  "complexity": "medium",
  "estimated_tasks": 4,
  "needs_architecture": true,
  "needs_testing": true,
  "primary_language": "python"
}}
```'''

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        fast_model: str = "codestral:latest",
        smart_model: str = "qwen3-coder:30b"
    ):
        self.ollama_url = ollama_url
        self.fast_model = fast_model
        self.smart_model = smart_model
        self.client = httpx.Client(timeout=120.0)

    def _call_llm(self, prompt: str, model: str = None) -> str:
        """Вызов LLM через Ollama API"""
        model = model or self.fast_model

        response = self.client.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.3,
                    "num_predict": 2048,
                }
            }
        )
        response.raise_for_status()
        return response.json()["response"]

    def _extract_json(self, text: str) -> dict:
        """Извлечь JSON из текста"""
        # Ищем JSON блок
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Пробуем весь текст как JSON
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Ищем первую { и последнюю }
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1:
            try:
                return json.loads(text[start:end+1])
            except json.JSONDecodeError:
                pass

        return {}

    def classify_task(self, task_description: str) -> dict:
        """
        Быстрая классификация задачи

        Returns:
            dict с полями: workflow_type, complexity, estimated_tasks, etc.
        """
        prompt = self.CLASSIFICATION_PROMPT.format(
            task_description=task_description
        )

        response = self._call_llm(prompt, self.fast_model)
        result = self._extract_json(response)

        # Значения по умолчанию
        defaults = {
            "workflow_type": "feature",
            "complexity": "medium",
            "estimated_tasks": 3,
            "needs_architecture": True,
            "needs_testing": True,
            "primary_language": "python"
        }

        return {**defaults, **result}

    def decompose_task(
        self,
        task_description: str,
        project_context: str = ""
    ) -> TaskGraph:
        """
        Декомпозиция задачи на подзадачи

        Args:
            task_description: Описание задачи от пользователя
            project_context: Контекст проекта (структура, паттерны)

        Returns:
            TaskGraph с задачами и зависимостями
        """
        prompt = self.DECOMPOSITION_PROMPT.format(
            task_description=task_description,
            project_context=project_context or "Контекст не предоставлен"
        )

        # Используем умную модель для декомпозиции
        response = self._call_llm(prompt, self.smart_model)
        result = self._extract_json(response)

        # Создаём граф задач
        graph = TaskGraph()

        tasks_data = result.get("tasks", [])

        for task_data in tasks_data:
            task = Task(
                id=task_data.get("id", f"task_{len(graph.tasks)+1}"),
                title=task_data.get("title", "Untitled"),
                description=task_data.get("description", ""),
                type=TaskType(task_data.get("type", "implementation")),
                priority=TaskPriority(task_data.get("priority", 3)),
                depends_on=task_data.get("depends_on", []),
                files_to_read=task_data.get("files_to_read", []),
                files_to_modify=task_data.get("files_to_modify", []),
            )
            graph.add_task(task)

        # Установить root task
        if graph.tasks:
            # Root — задача без зависимостей
            for task_id, task in graph.tasks.items():
                if not task.depends_on:
                    graph.root_task_id = task_id
                    break

        return graph

    def create_simple_task(
        self,
        task_description: str,
        task_type: TaskType = TaskType.IMPLEMENTATION
    ) -> TaskGraph:
        """
        Создать простую задачу без декомпозиции

        Для быстрых операций, не требующих LLM
        """
        task = Task(
            id="task_1",
            title=task_description[:50],
            description=task_description,
            type=task_type,
            priority=TaskPriority.MEDIUM,
        )

        graph = TaskGraph()
        graph.add_task(task)
        graph.root_task_id = task.id

        return graph

    def estimate_complexity(self, graph: TaskGraph) -> dict:
        """
        Оценка сложности плана

        Returns:
            dict: {
                "total_tasks": int,
                "parallel_groups": int,
                "estimated_time_minutes": int,
                "models_needed": list
            }
        """
        total = len(graph.tasks)

        # Группы параллельных задач
        order = graph.get_execution_order()
        groups = []
        current_group = []
        completed = set()

        for task_id in order:
            task = graph.tasks[task_id]
            if task.is_ready(completed):
                current_group.append(task_id)
            else:
                if current_group:
                    groups.append(current_group)
                    completed.update(current_group)
                current_group = [task_id]

        if current_group:
            groups.append(current_group)

        # Модели для разных типов задач
        models_map = {
            TaskType.ARCHITECTURE: "deepseek-r1:32b",
            TaskType.IMPLEMENTATION: "qwen3-coder:30b",
            TaskType.REFACTORING: "qwen3-coder:30b",
            TaskType.BUGFIX: "qwen3-coder:30b",
            TaskType.TESTING: "qwen3-coder:30b",
            TaskType.REVIEW: "deepseek-r1:32b",
            TaskType.DOCUMENTATION: "qwen3:8b",
            TaskType.DEVOPS: "qwen3-coder:30b",
            TaskType.RESEARCH: "deepseek-r1:32b",
        }

        models_needed = list(set(
            models_map.get(t.type, "qwen3-coder:30b")
            for t in graph.tasks.values()
        ))

        # Примерное время (2-5 минут на задачу)
        estimated_time = total * 3

        return {
            "total_tasks": total,
            "parallel_groups": len(groups),
            "execution_groups": groups,
            "estimated_time_minutes": estimated_time,
            "models_needed": models_needed,
        }


# CLI для тестирования
if __name__ == "__main__":
    import sys

    parser = TaskParser()

    if len(sys.argv) > 1:
        task_desc = " ".join(sys.argv[1:])
    else:
        task_desc = "Добавить аутентификацию с JWT токенами"

    print(f"📝 Задача: {task_desc}\n")

    # Классификация
    print("🔍 Классификация...")
    classification = parser.classify_task(task_desc)
    print(f"   Тип: {classification['workflow_type']}")
    print(f"   Сложность: {classification['complexity']}")
    print(f"   Примерно задач: {classification['estimated_tasks']}")

    # Декомпозиция
    print("\n📋 Декомпозиция...")
    graph = parser.decompose_task(task_desc)

    print(f"\n📊 Создано задач: {len(graph.tasks)}")
    for task in graph.tasks.values():
        deps = f" (depends: {task.depends_on})" if task.depends_on else ""
        print(f"   [{task.type.value}] {task.title}{deps}")

    # Оценка
    estimate = parser.estimate_complexity(graph)
    print(f"\n⏱️ Оценка:")
    print(f"   Групп параллельного выполнения: {estimate['parallel_groups']}")
    print(f"   Примерное время: {estimate['estimated_time_minutes']} мин")
    print(f"   Модели: {estimate['models_needed']}")

    # Mermaid диаграмма
    print(f"\n📈 Диаграмма:\n{graph.to_mermaid()}")
