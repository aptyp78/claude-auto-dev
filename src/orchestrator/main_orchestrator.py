"""
Main Orchestrator

Главный координатор Local Swarm системы.
Связывает все компоненты: TaskParser, ModelRouter, AgentRouter, Executor, RAG.
"""

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any

from .task_parser import TaskParser, TaskGraph, Task, TaskType, TaskStatus
from .model_router import ModelRouter
from .agent_router import AgentRouter, AgentType
from .executor import ExecutionScheduler, ExecutionResult, ExecutionMode


@dataclass
class OrchestratorConfig:
    """Конфигурация оркестратора"""
    # Ollama
    ollama_url: str = "http://localhost:11434"

    # Параллельность
    max_parallel_tasks: int = 2
    max_retries: int = 3

    # Модели (доступные в системе)
    fast_model: str = "codestral:latest"
    smart_model: str = "devstral:latest"  # Быстрее чем 30B

    # Quality Gates
    enable_review: bool = True
    enable_testing: bool = True
    require_human_approval: bool = False  # Автономный режим

    # RAG
    enable_rag: bool = True
    rag_top_k: int = 10


@dataclass
class OrchestratorState:
    """Состояние оркестратора"""
    current_task: Optional[str] = None
    phase: str = "idle"  # idle, planning, building, testing, reviewing, deploying
    task_graph: Optional[TaskGraph] = None
    results: Dict[str, ExecutionResult] = field(default_factory=dict)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class LocalSwarmOrchestrator:
    """
    Главный оркестратор Local Swarm

    Workflow:
    1. PARSE: Получить задачу от пользователя
    2. CLASSIFY: Определить тип и сложность
    3. DECOMPOSE: Разбить на подзадачи
    4. [APPROVAL]: Получить одобрение плана
    5. EXECUTE: Выполнить задачи (параллельно где возможно)
    6. REVIEW: Провести code review
    7. TEST: Запустить тесты
    8. [APPROVAL]: Одобрение деплоя
    9. COMPLETE: Завершение
    """

    def __init__(
        self,
        config: Optional[OrchestratorConfig] = None,
        rag_retriever: Optional[Callable[[str], str]] = None
    ):
        self.config = config or OrchestratorConfig()

        # Компоненты
        self.task_parser = TaskParser(
            ollama_url=self.config.ollama_url,
            fast_model=self.config.fast_model,
            smart_model=self.config.smart_model
        )
        self.model_router = ModelRouter(self.config.ollama_url)
        self.agent_router = AgentRouter()
        self.executor = ExecutionScheduler(
            ollama_url=self.config.ollama_url,
            max_parallel=self.config.max_parallel_tasks,
            max_retries=self.config.max_retries,
            mode=ExecutionMode.PARALLEL
        )

        # RAG
        self.rag_retriever = rag_retriever

        # Состояние
        self.state = OrchestratorState()

        # Callbacks
        self.on_phase_change: Optional[Callable[[str], None]] = None
        self.on_task_complete: Optional[Callable[[Task, ExecutionResult], None]] = None
        self.on_approval_needed: Optional[Callable[[str, dict], bool]] = None

    def _set_phase(self, phase: str) -> None:
        """Изменить фазу"""
        self.state.phase = phase
        if self.on_phase_change:
            self.on_phase_change(phase)
        print(f"\n{'='*50}")
        print(f"📍 Phase: {phase.upper()}")
        print(f"{'='*50}")

    def _request_approval(self, checkpoint: str, data: dict) -> bool:
        """Запросить одобрение пользователя"""
        if not self.config.require_human_approval:
            return True

        if self.on_approval_needed:
            return self.on_approval_needed(checkpoint, data)

        # CLI fallback
        print(f"\n⭐ CHECKPOINT: {checkpoint}")
        print(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        response = input("\n✅ Approve? (y/n): ").strip().lower()
        return response in ["y", "yes", "да"]

    def classify_task(self, task_description: str) -> dict:
        """
        Phase 1: Классификация задачи

        Returns:
            dict: workflow_type, complexity, etc.
        """
        self._set_phase("classifying")

        classification = self.task_parser.classify_task(task_description)

        print(f"  Type: {classification['workflow_type']}")
        print(f"  Complexity: {classification['complexity']}")
        print(f"  Estimated tasks: {classification['estimated_tasks']}")

        return classification

    def decompose_task(
        self,
        task_description: str,
        project_context: str = ""
    ) -> TaskGraph:
        """
        Phase 2: Декомпозиция на подзадачи

        Returns:
            TaskGraph
        """
        self._set_phase("planning")

        # Если есть RAG — получить контекст
        if self.rag_retriever and self.config.enable_rag:
            rag_context = self.rag_retriever(task_description)
            project_context = f"{project_context}\n\nRelevant code:\n{rag_context}"

        graph = self.task_parser.decompose_task(task_description, project_context)
        self.state.task_graph = graph

        # Показать план
        print(f"\n📋 Plan created: {len(graph.tasks)} tasks")
        for task in graph.tasks.values():
            deps = f" → depends on: {task.depends_on}" if task.depends_on else ""
            print(f"  [{task.type.value}] {task.title}{deps}")

        # Оценка
        estimate = self.task_parser.estimate_complexity(graph)
        print(f"\n⏱️ Estimate: {estimate['estimated_time_minutes']} minutes")
        print(f"   Parallel groups: {estimate['parallel_groups']}")

        # Mermaid диаграмма
        print(f"\n📈 Dependency graph:")
        print(graph.to_mermaid())

        return graph

    def approve_plan(self, graph: TaskGraph) -> bool:
        """
        Phase 3: Одобрение плана

        Returns:
            bool: одобрен ли план
        """
        estimate = self.task_parser.estimate_complexity(graph)

        data = {
            "total_tasks": len(graph.tasks),
            "tasks": [t.to_dict() for t in graph.tasks.values()],
            "estimated_time_minutes": estimate["estimated_time_minutes"],
            "models_needed": estimate["models_needed"],
        }

        return self._request_approval("Plan Approval", data)

    def execute_plan(
        self,
        graph: TaskGraph,
        project_context: str = ""
    ) -> Dict[str, ExecutionResult]:
        """
        Phase 4: Выполнение плана

        Returns:
            Dict task_id -> ExecutionResult
        """
        self._set_phase("building")

        self.state.started_at = datetime.now()

        # Настроить callbacks
        def on_complete(task: Task, result: ExecutionResult):
            status = "✅" if result.success else "❌"
            print(f"  {status} [{task.type.value}] {task.title} ({result.execution_time_seconds:.1f}s)")
            if self.on_task_complete:
                self.on_task_complete(task, result)

        self.executor.on_task_complete = on_complete

        # Выполнить
        results = self.executor.execute_graph(
            graph,
            project_context=project_context,
            rag_retriever=self.rag_retriever if self.config.enable_rag else None
        )

        self.state.results = results
        return results

    def run_review(self, results: Dict[str, ExecutionResult]) -> ExecutionResult:
        """
        Phase 5: Code Review

        Returns:
            ExecutionResult от Reviewer агента
        """
        if not self.config.enable_review:
            return ExecutionResult(task_id="review", success=True, output="Review skipped")

        self._set_phase("reviewing")

        # Собрать код для review
        code_to_review = []
        for task_id, result in results.items():
            if result.success and result.output:
                code_to_review.append(f"## {task_id}\n{result.output}")

        review_content = "\n\n".join(code_to_review)

        # Создать задачу для review
        review_task = Task(
            id="review",
            title="Code Review",
            description=f"Проведи code review следующего кода:\n\n{review_content}",
            type=TaskType.REVIEW,
        )

        # Выполнить
        return self.executor.execute_task(review_task)

    def run_tests(self, results: Dict[str, ExecutionResult]) -> ExecutionResult:
        """
        Phase 6: Тестирование

        Returns:
            ExecutionResult от Tester агента
        """
        if not self.config.enable_testing:
            return ExecutionResult(task_id="testing", success=True, output="Testing skipped")

        self._set_phase("testing")

        # Создать задачу для тестирования
        test_task = Task(
            id="testing",
            title="Generate and Run Tests",
            description="Напиши и запусти тесты для реализованного кода",
            type=TaskType.TESTING,
        )

        return self.executor.execute_task(test_task)

    def approve_deploy(self, summary: dict) -> bool:
        """
        Phase 7: Одобрение деплоя

        Returns:
            bool: одобрен ли деплой
        """
        return self._request_approval("Deploy Approval", summary)

    def run(
        self,
        task_description: str,
        project_context: str = ""
    ) -> dict:
        """
        Полный цикл выполнения задачи

        Args:
            task_description: Описание задачи
            project_context: Контекст проекта

        Returns:
            dict: Результаты выполнения
        """
        print(f"\n🚀 Local Swarm Orchestrator")
        print(f"📝 Task: {task_description}")

        # Phase 1: Classify
        classification = self.classify_task(task_description)

        # Phase 2: Decompose
        graph = self.decompose_task(task_description, project_context)

        # Phase 3: Approve Plan
        if not self.approve_plan(graph):
            print("\n❌ Plan rejected by user")
            return {"status": "rejected", "phase": "planning"}

        # Phase 4: Execute
        results = self.execute_plan(graph, project_context)

        # Проверить на failures
        failed = [r for r in results.values() if not r.success]
        if failed:
            print(f"\n⚠️ {len(failed)} tasks failed")
            for r in failed:
                print(f"  ❌ {r.task_id}: {r.error}")

        # Phase 5: Review
        review_result = self.run_review(results)
        if not review_result.success:
            print(f"\n⚠️ Review found issues: {review_result.output[:200]}")

        # Phase 6: Test (если были implementation задачи)
        has_code = any(
            results[t.id].success for t in graph.tasks.values()
            if t.type in [TaskType.IMPLEMENTATION, TaskType.REFACTORING, TaskType.BUGFIX]
        )
        if has_code:
            test_result = self.run_tests(results)
            if not test_result.success:
                print(f"\n⚠️ Tests failed: {test_result.error}")

        # Summary
        self.state.completed_at = datetime.now()
        summary = self.executor.get_summary()
        summary["classification"] = classification
        summary["review"] = review_result.to_dict() if review_result else None

        # Phase 7: Approve Deploy
        self._set_phase("deploying")
        if not self.approve_deploy(summary):
            print("\n⏸️ Deploy postponed by user")
            return {"status": "pending_deploy", **summary}

        # Done
        self._set_phase("completed")
        print(f"\n✅ Completed!")
        print(f"   Tasks: {summary['successful']}/{summary['total_tasks']} successful")
        print(f"   Time: {summary['total_time_seconds']:.1f}s")
        print(f"   Tokens: {summary['total_tokens']}")

        return {"status": "completed", **summary}


def create_orchestrator(
    config_path: Optional[str] = None,
    **kwargs
) -> LocalSwarmOrchestrator:
    """
    Фабрика для создания оркестратора

    Args:
        config_path: Путь к YAML конфигу
        **kwargs: Override параметры

    Returns:
        LocalSwarmOrchestrator
    """
    config = OrchestratorConfig(**kwargs)

    if config_path:
        import yaml
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f)
            for key, value in yaml_config.get("orchestrator", {}).items():
                if hasattr(config, key):
                    setattr(config, key, value)

    return LocalSwarmOrchestrator(config)


# CLI
if __name__ == "__main__":
    # Проверить аргументы
    if len(sys.argv) < 2:
        print("Usage: python -m orchestrator.main_orchestrator 'task description'")
        print("\nExample:")
        print("  python -m orchestrator.main_orchestrator 'Добавить endpoint /health'")
        sys.exit(1)

    task_desc = " ".join(sys.argv[1:])

    # Создать оркестратор
    orchestrator = create_orchestrator(
        require_human_approval=True,
        enable_review=True,
        enable_testing=True
    )

    # Запустить
    result = orchestrator.run(task_desc)

    # Вывести результат
    print("\n" + "=" * 50)
    print("📊 Final Result:")
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
