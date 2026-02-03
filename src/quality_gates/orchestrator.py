"""
Quality Gate Orchestrator

Координирует выполнение всех quality gates.
Поддерживает параллельное выполнение, retry и fail-fast.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Callable
from pathlib import Path

from .base import QualityGate, GateResult, GateSeverity
from .linter import LinterGate
from .test_runner import TestRunnerGate
from .security_scanner import SecurityScannerGate
from .coverage_checker import CoverageCheckerGate


@dataclass
class PipelineResult:
    """Результат выполнения всего pipeline"""
    passed: bool
    gate_results: List[GateResult] = field(default_factory=list)

    # Статистика
    total_gates: int = 0
    passed_gates: int = 0
    failed_gates: int = 0

    # Время
    total_execution_time: float = 0.0

    # Ошибка (если была)
    error: Optional[str] = None
    stopped_at_gate: Optional[str] = None

    @property
    def blocking_failures(self) -> List[GateResult]:
        """Gates которые заблокировали pipeline"""
        return [r for r in self.gate_results if not r.passed and r.blocking]

    @property
    def warnings(self) -> List[GateResult]:
        """Gates с предупреждениями (non-blocking)"""
        return [r for r in self.gate_results if not r.passed and not r.blocking]

    def summary(self) -> str:
        """Полная сводка по pipeline"""
        lines = []

        # Общий статус
        status = "✅ PIPELINE PASSED" if self.passed else "❌ PIPELINE FAILED"
        lines.append(f"\n{'='*50}")
        lines.append(status)
        lines.append(f"{'='*50}")

        # Статистика
        lines.append(f"\nGates: {self.passed_gates}/{self.total_gates} passed")
        lines.append(f"Time: {self.total_execution_time:.1f}s")

        # Результаты каждого gate
        lines.append("\n--- Gate Results ---")
        for result in self.gate_results:
            icon = "✅" if result.passed else ("❌" if result.blocking else "⚠️")
            blocking = " [BLOCKING]" if result.blocking and not result.passed else ""
            lines.append(f"{icon} {result.gate_name}: {result.execution_time_seconds:.1f}s{blocking}")

            if result.issues:
                critical = len(result.critical_issues)
                errors = len(result.error_issues)
                warnings = len(result.warning_issues)
                lines.append(f"   Issues: {critical} critical, {errors} errors, {warnings} warnings")

            if result.auto_fixed_count > 0:
                lines.append(f"   Auto-fixed: {result.auto_fixed_count}")

        # Если остановились на gate
        if self.stopped_at_gate:
            lines.append(f"\n⛔ Pipeline stopped at: {self.stopped_at_gate}")

        # Ошибка
        if self.error:
            lines.append(f"\n🚨 Error: {self.error}")

        lines.append(f"{'='*50}\n")

        return "\n".join(lines)


class QualityGateOrchestrator:
    """
    Оркестратор quality gates

    Порядок выполнения (от быстрых к медленным):
    1. Linter (быстро, с auto-fix)
    2. Security Scanner (быстро, критично)
    3. Test Runner (медленно, критично)
    4. Coverage Checker (медленно, информативно)
    """

    # Порядок выполнения по умолчанию
    DEFAULT_GATE_ORDER = [
        "linter",
        "security",
        "tests",
        "coverage",
    ]

    def __init__(
        self,
        fail_fast: bool = True,
        parallel: bool = False,
        auto_fix: bool = True
    ):
        """
        Args:
            fail_fast: Остановить pipeline на первом blocking failure
            parallel: Запускать независимые gates параллельно
            auto_fix: Включить авто-исправление для поддерживаемых gates
        """
        self.fail_fast = fail_fast
        self.parallel = parallel
        self.auto_fix = auto_fix

        # Инициализация gates
        self.gates: Dict[str, QualityGate] = {}
        self._init_default_gates()

        # Callbacks
        self.on_gate_start: Optional[Callable[[str], None]] = None
        self.on_gate_complete: Optional[Callable[[GateResult], None]] = None

    def _init_default_gates(self):
        """Инициализация стандартных gates"""
        self.gates = {
            "linter": LinterGate(
                blocking=True,
                auto_fix=self.auto_fix,
                ignore_warnings=False
            ),
            "security": SecurityScannerGate(
                blocking=True,
                scan_secrets=True,
                min_severity="medium"
            ),
            "tests": TestRunnerGate(
                blocking=True,
                parallel=True,
                timeout=300
            ),
            "coverage": CoverageCheckerGate(
                blocking=False,  # Coverage не блокирует по умолчанию
                min_coverage=70.0,
                critical_coverage=90.0
            ),
        }

    def configure_gate(
        self,
        gate_name: str,
        **kwargs
    ):
        """
        Настроить gate

        Args:
            gate_name: Имя gate (linter, security, tests, coverage)
            **kwargs: Параметры для настройки
        """
        if gate_name not in self.gates:
            raise ValueError(f"Unknown gate: {gate_name}")

        gate = self.gates[gate_name]

        # Обновляем атрибуты
        for key, value in kwargs.items():
            if hasattr(gate, key):
                setattr(gate, key, value)

    def add_gate(self, name: str, gate: QualityGate):
        """Добавить кастомный gate"""
        self.gates[name] = gate

    def remove_gate(self, name: str):
        """Удалить gate"""
        if name in self.gates:
            del self.gates[name]

    async def _run_gate(
        self,
        name: str,
        gate: QualityGate,
        context: Dict[str, Any]
    ) -> GateResult:
        """Запустить один gate"""
        # Callback: start
        if self.on_gate_start:
            self.on_gate_start(name)

        try:
            # Запуск с auto-fix если поддерживается
            if self.auto_fix and gate.auto_fix:
                result = await gate.check_and_fix(context)
            else:
                result = await gate.check(context)

        except Exception as e:
            # Ошибка выполнения
            result = GateResult(
                gate_name=gate.name,
                passed=False,
                blocking=gate.blocking,
                error=str(e),
            )

        # Callback: complete
        if self.on_gate_complete:
            self.on_gate_complete(result)

        return result

    async def run(
        self,
        context: Dict[str, Any],
        gates: Optional[List[str]] = None
    ) -> PipelineResult:
        """
        Запустить pipeline quality gates

        Args:
            context: Контекст (project_path, files_changed, etc.)
            gates: Список gates для запуска (None = все)

        Returns:
            PipelineResult
        """
        start_time = time.time()

        # Определяем какие gates запускать
        gate_order = gates or self.DEFAULT_GATE_ORDER
        active_gates = [(name, self.gates[name]) for name in gate_order if name in self.gates]

        results: List[GateResult] = []
        stopped_at = None
        error = None

        if self.parallel and not self.fail_fast:
            # Параллельное выполнение
            tasks = [
                self._run_gate(name, gate, context)
                for name, gate in active_gates
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # Обработка исключений
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    gate_name = active_gates[i][0]
                    results[i] = GateResult(
                        gate_name=gate_name,
                        passed=False,
                        blocking=True,
                        error=str(result),
                    )
        else:
            # Последовательное выполнение с fail-fast
            for name, gate in active_gates:
                try:
                    result = await self._run_gate(name, gate, context)
                    results.append(result)

                    # Fail-fast: остановка на blocking failure
                    if self.fail_fast and not result.passed and result.blocking:
                        stopped_at = name
                        break

                except Exception as e:
                    error = str(e)
                    results.append(GateResult(
                        gate_name=gate.name,
                        passed=False,
                        blocking=gate.blocking,
                        error=str(e),
                    ))
                    if self.fail_fast:
                        stopped_at = name
                        break

        # Подсчёт статистики
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        failed = total - passed

        # Определяем общий результат
        # Pipeline passed если нет blocking failures
        pipeline_passed = all(
            r.passed or not r.blocking
            for r in results
        )

        total_time = time.time() - start_time

        return PipelineResult(
            passed=pipeline_passed,
            gate_results=results,
            total_gates=total,
            passed_gates=passed,
            failed_gates=failed,
            total_execution_time=total_time,
            error=error,
            stopped_at_gate=stopped_at,
        )

    async def run_quick(self, context: Dict[str, Any]) -> PipelineResult:
        """
        Быстрая проверка (только linter и security)

        Используется для быстрой валидации перед полной проверкой.
        """
        return await self.run(context, gates=["linter", "security"])

    async def run_full(self, context: Dict[str, Any]) -> PipelineResult:
        """
        Полная проверка (все gates)
        """
        return await self.run(context, gates=self.DEFAULT_GATE_ORDER)

    async def run_pre_commit(self, context: Dict[str, Any]) -> PipelineResult:
        """
        Pre-commit проверка (linter с auto-fix, security)

        Оптимизирована для быстрого выполнения перед коммитом.
        """
        # Временно делаем coverage non-blocking
        original_blocking = self.gates.get("tests", None)
        if original_blocking:
            original_blocking = self.gates["tests"].blocking

        result = await self.run(context, gates=["linter", "security"])

        return result

    async def run_ci(self, context: Dict[str, Any]) -> PipelineResult:
        """
        CI/CD проверка (все gates, без auto-fix)

        Строгая проверка для CI без автоматических исправлений.
        """
        # Отключаем auto-fix для CI
        original_auto_fix = self.auto_fix
        self.auto_fix = False

        # Делаем все gates blocking
        original_blocking = {}
        for name, gate in self.gates.items():
            original_blocking[name] = gate.blocking
            gate.blocking = True

        try:
            result = await self.run_full(context)
        finally:
            # Восстанавливаем настройки
            self.auto_fix = original_auto_fix
            for name, blocking in original_blocking.items():
                if name in self.gates:
                    self.gates[name].blocking = blocking

        return result


# Фабричные функции для удобства
def create_strict_pipeline() -> QualityGateOrchestrator:
    """Строгий pipeline (все gates blocking, без auto-fix)"""
    orchestrator = QualityGateOrchestrator(
        fail_fast=True,
        parallel=False,
        auto_fix=False
    )

    # Делаем все gates blocking
    for gate in orchestrator.gates.values():
        gate.blocking = True

    return orchestrator


def create_lenient_pipeline() -> QualityGateOrchestrator:
    """Мягкий pipeline (auto-fix, coverage non-blocking)"""
    orchestrator = QualityGateOrchestrator(
        fail_fast=False,
        parallel=True,
        auto_fix=True
    )

    # Coverage и linter не блокируют
    orchestrator.gates["coverage"].blocking = False

    return orchestrator


def create_quick_pipeline() -> QualityGateOrchestrator:
    """Быстрый pipeline (только linter и security)"""
    orchestrator = QualityGateOrchestrator(
        fail_fast=True,
        parallel=False,
        auto_fix=True
    )

    # Удаляем медленные gates
    orchestrator.remove_gate("tests")
    orchestrator.remove_gate("coverage")

    return orchestrator


# CLI для тестирования
if __name__ == "__main__":
    import sys

    async def main():
        project_path = sys.argv[1] if len(sys.argv) > 1 else "."
        mode = sys.argv[2] if len(sys.argv) > 2 else "full"

        print(f"Running quality gates on: {project_path}")
        print(f"Mode: {mode}")
        print()

        orchestrator = QualityGateOrchestrator(
            fail_fast=True,
            auto_fix=True
        )

        # Callbacks для прогресса
        orchestrator.on_gate_start = lambda name: print(f"⏳ Running: {name}...")
        orchestrator.on_gate_complete = lambda r: print(f"   {'✅' if r.passed else '❌'} {r.gate_name}")

        context = {"project_path": project_path}

        if mode == "quick":
            result = await orchestrator.run_quick(context)
        elif mode == "ci":
            result = await orchestrator.run_ci(context)
        else:
            result = await orchestrator.run_full(context)

        print(result.summary())

        # Exit code
        sys.exit(0 if result.passed else 1)

    asyncio.run(main())
