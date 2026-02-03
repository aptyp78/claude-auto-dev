"""
Execution Scheduler

Выполняет задачи параллельно или последовательно,
управляет контекстом и интегрируется с LLM.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Callable, Any
from concurrent.futures import ThreadPoolExecutor
import httpx

from .task_parser import Task, TaskGraph, TaskStatus, TaskType
from .model_router import ModelRouter, ModelConfig
from .agent_router import AgentRouter, AgentConfig, AgentType


class ExecutionMode(Enum):
    """Режимы выполнения"""
    SEQUENTIAL = "sequential"    # Последовательно
    PARALLEL = "parallel"        # Параллельно где возможно
    INTERACTIVE = "interactive"  # С подтверждениями


@dataclass
class ExecutionResult:
    """Результат выполнения задачи"""
    task_id: str
    success: bool
    output: str = ""
    error: Optional[str] = None

    # Метрики
    tokens_used: int = 0
    execution_time_seconds: float = 0
    model_used: str = ""
    agent_used: str = ""

    # Артефакты
    files_created: List[str] = field(default_factory=list)
    files_modified: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "output": self.output[:500] if self.output else "",
            "error": self.error,
            "tokens_used": self.tokens_used,
            "execution_time": self.execution_time_seconds,
            "model": self.model_used,
            "agent": self.agent_used,
        }


@dataclass
class ExecutionContext:
    """Контекст выполнения"""
    task: Task
    agent: AgentConfig
    model: ModelConfig

    # RAG контекст
    relevant_code: str = ""
    project_memories: str = ""

    # История
    previous_results: List[ExecutionResult] = field(default_factory=list)

    # Ограничения
    max_tokens: int = 32000
    timeout_seconds: int = 300


class LLMClient:
    """Клиент для работы с Ollama"""

    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.client = httpx.Client(timeout=300.0)

    def generate(
        self,
        prompt: str,
        model: str,
        system: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Генерация через Ollama API

        Returns:
            dict: {"response": str, "tokens": int, "time": float}
        """
        start_time = time.time()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            response = self.client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    }
                }
            )
            response.raise_for_status()
            data = response.json()

            elapsed = time.time() - start_time

            return {
                "response": data.get("message", {}).get("content", ""),
                "tokens": data.get("eval_count", 0) + data.get("prompt_eval_count", 0),
                "time": elapsed,
                "model": model,
            }

        except Exception as e:
            return {
                "response": "",
                "error": str(e),
                "tokens": 0,
                "time": time.time() - start_time,
                "model": model,
            }

    def check_health(self) -> bool:
        """Проверить доступность Ollama"""
        try:
            response = self.client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except:
            return False


class ExecutionScheduler:
    """
    Планировщик выполнения задач

    Управляет:
    - Параллельным выполнением независимых задач
    - Выбором моделей и агентов
    - Сборкой контекста
    - Retry логикой
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        max_parallel: int = 2,
        max_retries: int = 3,
        mode: ExecutionMode = ExecutionMode.PARALLEL
    ):
        self.llm = LLMClient(ollama_url)
        self.model_router = ModelRouter(ollama_url)
        self.agent_router = AgentRouter()

        self.max_parallel = max_parallel
        self.max_retries = max_retries
        self.mode = mode

        self.executor = ThreadPoolExecutor(max_workers=max_parallel)

        # Callbacks
        self.on_task_start: Optional[Callable[[Task], None]] = None
        self.on_task_complete: Optional[Callable[[Task, ExecutionResult], None]] = None
        self.on_human_approval: Optional[Callable[[str], bool]] = None

        # Результаты
        self.results: Dict[str, ExecutionResult] = {}

    def _build_prompt(
        self,
        context: ExecutionContext
    ) -> str:
        """Построить промпт для выполнения задачи"""
        parts = []

        # Описание задачи
        parts.append(f"## Задача: {context.task.title}")
        parts.append(f"\n{context.task.description}")

        # Файлы для работы
        if context.task.files_to_read:
            parts.append(f"\n## Файлы для чтения:\n- " + "\n- ".join(context.task.files_to_read))

        if context.task.files_to_modify:
            parts.append(f"\n## Файлы для изменения:\n- " + "\n- ".join(context.task.files_to_modify))

        # RAG контекст
        if context.relevant_code:
            parts.append(f"\n## Релевантный код:\n```\n{context.relevant_code}\n```")

        # Память проекта
        if context.project_memories:
            parts.append(f"\n## Память проекта:\n{context.project_memories}")

        # Предыдущие результаты
        if context.previous_results:
            parts.append("\n## Предыдущие шаги:")
            for result in context.previous_results[-3:]:  # Последние 3
                status = "✅" if result.success else "❌"
                parts.append(f"- {status} {result.task_id}: {result.output[:200]}...")

        return "\n".join(parts)

    def _execute_single_task(
        self,
        task: Task,
        context: ExecutionContext
    ) -> ExecutionResult:
        """Выполнить одну задачу"""
        start_time = time.time()

        # Callback: начало
        if self.on_task_start:
            self.on_task_start(task)

        # Построить промпт
        prompt = self._build_prompt(context)

        # Вызвать LLM
        llm_result = self.llm.generate(
            prompt=prompt,
            model=context.model.name,
            system=context.agent.system_prompt,
            temperature=context.agent.temperature,
            max_tokens=context.agent.max_tokens,
        )

        elapsed = time.time() - start_time

        # Проверить на ошибку
        if "error" in llm_result:
            result = ExecutionResult(
                task_id=task.id,
                success=False,
                error=llm_result["error"],
                execution_time_seconds=elapsed,
                model_used=context.model.name,
                agent_used=context.agent.name,
            )
        else:
            result = ExecutionResult(
                task_id=task.id,
                success=True,
                output=llm_result["response"],
                tokens_used=llm_result["tokens"],
                execution_time_seconds=elapsed,
                model_used=context.model.name,
                agent_used=context.agent.name,
            )

        # Callback: завершение
        if self.on_task_complete:
            self.on_task_complete(task, result)

        return result

    def _execute_with_retry(
        self,
        task: Task,
        project_context: str = "",
        rag_context: str = ""
    ) -> ExecutionResult:
        """Выполнить задачу с retry логикой"""
        # Выбрать агента
        agent = self.agent_router.select_agent(
            task.type.value,
            task.description
        )

        # Выбрать модель
        model, reason = self.model_router.select_model(
            task.type.value,
            complexity="medium"
        )

        # Создать контекст
        context = ExecutionContext(
            task=task,
            agent=agent,
            model=model,
            relevant_code=rag_context,
            project_memories=project_context,
        )

        last_error = None
        for attempt in range(self.max_retries):
            result = self._execute_single_task(task, context)

            if result.success:
                return result

            last_error = result.error
            print(f"  ⚠️ Attempt {attempt + 1} failed: {last_error}")

            # Для retry используем другого агента или модель
            if attempt == 1:
                # Попробовать fallback модель
                fallback_model = self.model_router.models.get(agent.fallback_model)
                if fallback_model:
                    context.model = fallback_model
                    print(f"  🔄 Switching to fallback model: {fallback_model.name}")

            elif attempt == 2:
                # Попробовать другого агента
                retry_agent = self.agent_router.get_agent_for_retry(
                    agent.type,
                    last_error or ""
                )
                context.agent = retry_agent
                print(f"  🔄 Switching to retry agent: {retry_agent.name}")

        # Все попытки исчерпаны
        return ExecutionResult(
            task_id=task.id,
            success=False,
            error=f"All {self.max_retries} attempts failed. Last error: {last_error}",
            model_used=context.model.name,
            agent_used=context.agent.name,
        )

    def execute_task(
        self,
        task: Task,
        project_context: str = "",
        rag_context: str = ""
    ) -> ExecutionResult:
        """
        Выполнить одну задачу

        Args:
            task: Задача для выполнения
            project_context: Контекст проекта
            rag_context: Контекст из RAG

        Returns:
            ExecutionResult
        """
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = datetime.now()

        result = self._execute_with_retry(task, project_context, rag_context)

        task.result = result.output if result.success else None
        task.error = result.error
        task.status = TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
        task.completed_at = datetime.now()

        self.results[task.id] = result
        return result

    async def execute_graph_async(
        self,
        graph: TaskGraph,
        project_context: str = "",
        rag_retriever: Optional[Callable[[str], str]] = None
    ) -> Dict[str, ExecutionResult]:
        """
        Асинхронное выполнение графа задач

        Args:
            graph: Граф задач
            project_context: Контекст проекта
            rag_retriever: Функция для получения RAG контекста

        Returns:
            Dict task_id -> ExecutionResult
        """
        completed = set()
        results = {}

        while len(completed) < len(graph.tasks):
            # Найти готовые задачи
            ready_tasks = graph.get_ready_tasks(completed)

            if not ready_tasks:
                # Проверяем на deadlock
                pending = [t for t in graph.tasks.values()
                          if t.id not in completed]
                if pending:
                    print(f"⚠️ Deadlock detected. Pending tasks: {[t.id for t in pending]}")
                    break
                continue

            # Ограничить параллельность
            batch = ready_tasks[:self.max_parallel]

            print(f"\n📦 Executing batch of {len(batch)} tasks:")
            for task in batch:
                print(f"   - {task.id}: {task.title}")

            # Выполнить параллельно
            if self.mode == ExecutionMode.PARALLEL and len(batch) > 1:
                tasks_coro = []
                for task in batch:
                    # Получить RAG контекст если есть retriever
                    rag_context = ""
                    if rag_retriever:
                        rag_context = rag_retriever(task.description)

                    # Создать корутину
                    coro = asyncio.get_event_loop().run_in_executor(
                        self.executor,
                        self._execute_with_retry,
                        task,
                        project_context,
                        rag_context
                    )
                    tasks_coro.append((task, coro))

                # Ждать завершения
                for task, coro in tasks_coro:
                    result = await coro
                    results[task.id] = result
                    completed.add(task.id)

                    status = "✅" if result.success else "❌"
                    print(f"   {status} {task.id}: {result.execution_time_seconds:.1f}s")

            else:
                # Последовательное выполнение
                for task in batch:
                    rag_context = ""
                    if rag_retriever:
                        rag_context = rag_retriever(task.description)

                    result = self.execute_task(task, project_context, rag_context)
                    results[task.id] = result
                    completed.add(task.id)

                    status = "✅" if result.success else "❌"
                    print(f"   {status} {task.id}: {result.execution_time_seconds:.1f}s")

        self.results = results
        return results

    def execute_graph_sync(
        self,
        graph: TaskGraph,
        project_context: str = "",
        rag_retriever: Optional[Callable[[str], str]] = None
    ) -> Dict[str, ExecutionResult]:
        """
        Полностью синхронная версия выполнения графа задач
        Выполняет задачи последовательно с учётом зависимостей
        """
        completed = set()
        results = {}

        while len(completed) < len(graph.tasks):
            # Найти задачи, готовые к выполнению
            ready_tasks = [
                task for task in graph.tasks.values()
                if task.id not in completed
                and all(dep in completed for dep in task.depends_on)
            ]

            if not ready_tasks:
                # Deadlock или все выполнены
                remaining = set(graph.tasks.keys()) - completed
                if remaining:
                    print(f"⚠️ Deadlock: {remaining}")
                break

            print(f"\n📦 Executing {len(ready_tasks)} task(s):")
            for task in ready_tasks:
                print(f"   - {task.id}: {task.title}")

            # Последовательное выполнение
            for task in ready_tasks:
                rag_context = ""
                if rag_retriever:
                    rag_context = rag_retriever(task.description)

                result = self.execute_task(task, project_context, rag_context)
                results[task.id] = result
                completed.add(task.id)

                status = "✅" if result.success else "❌"
                print(f"   {status} {task.id}: {result.execution_time_seconds:.1f}s")

        self.results = results
        return results

    def execute_graph(
        self,
        graph: TaskGraph,
        project_context: str = "",
        rag_retriever: Optional[Callable[[str], str]] = None
    ) -> Dict[str, ExecutionResult]:
        """
        Синхронная версия выполнения графа задач
        """
        return self.execute_graph_sync(graph, project_context, rag_retriever)

    def get_summary(self) -> dict:
        """Получить сводку выполнения"""
        total = len(self.results)
        successful = sum(1 for r in self.results.values() if r.success)
        failed = total - successful

        total_tokens = sum(r.tokens_used for r in self.results.values())
        total_time = sum(r.execution_time_seconds for r in self.results.values())

        models_used = list(set(r.model_used for r in self.results.values()))
        agents_used = list(set(r.agent_used for r in self.results.values()))

        return {
            "total_tasks": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0,
            "total_tokens": total_tokens,
            "total_time_seconds": total_time,
            "models_used": models_used,
            "agents_used": agents_used,
        }


# CLI для тестирования
if __name__ == "__main__":
    from .task_parser import TaskParser

    # Проверяем Ollama
    scheduler = ExecutionScheduler()

    if not scheduler.llm.check_health():
        print("❌ Ollama not running. Please start: ollama serve")
        exit(1)

    print("✅ Ollama is running")

    # Создаём простую задачу
    parser = TaskParser()
    graph = parser.create_simple_task(
        "Напиши функцию для валидации email адреса на Python",
        TaskType.IMPLEMENTATION
    )

    print(f"\n📋 Task: {graph.tasks['task_1'].title}")

    # Выполняем
    results = scheduler.execute_graph(graph)

    # Результат
    print("\n📊 Results:")
    for task_id, result in results.items():
        status = "✅" if result.success else "❌"
        print(f"  {status} {task_id}")
        print(f"     Model: {result.model_used}")
        print(f"     Agent: {result.agent_used}")
        print(f"     Time: {result.execution_time_seconds:.1f}s")
        print(f"     Tokens: {result.tokens_used}")

        if result.success:
            print(f"\n📝 Output:\n{result.output[:500]}...")
        else:
            print(f"\n❌ Error: {result.error}")

    # Сводка
    summary = scheduler.get_summary()
    print(f"\n📈 Summary:")
    print(f"   Success rate: {summary['success_rate']*100:.0f}%")
    print(f"   Total tokens: {summary['total_tokens']}")
    print(f"   Total time: {summary['total_time_seconds']:.1f}s")
