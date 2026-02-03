"""
Base Quality Gate

Базовый класс для всех quality gates.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Dict, Any
from datetime import datetime


class GateSeverity(Enum):
    """Уровни серьёзности проблем"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class GateIssue:
    """Проблема, найденная gate"""
    severity: GateSeverity
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    code: Optional[str] = None  # Код правила (E501, W0611, etc.)
    suggestion: Optional[str] = None
    auto_fixable: bool = False

    def to_dict(self) -> dict:
        return {
            "severity": self.severity.value,
            "message": self.message,
            "file": self.file,
            "line": self.line,
            "code": self.code,
            "suggestion": self.suggestion,
            "auto_fixable": self.auto_fixable,
        }


@dataclass
class GateResult:
    """Результат проверки gate"""
    gate_name: str
    passed: bool
    blocking: bool = True  # Блокирует ли pipeline

    # Проблемы
    issues: List[GateIssue] = field(default_factory=list)

    # Статистика
    total_checks: int = 0
    passed_checks: int = 0
    failed_checks: int = 0

    # Метаданные
    execution_time_seconds: float = 0
    output: str = ""
    error: Optional[str] = None

    # Авто-исправления
    auto_fixed_count: int = 0

    # Время
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def critical_issues(self) -> List[GateIssue]:
        return [i for i in self.issues if i.severity == GateSeverity.CRITICAL]

    @property
    def error_issues(self) -> List[GateIssue]:
        return [i for i in self.issues if i.severity == GateSeverity.ERROR]

    @property
    def warning_issues(self) -> List[GateIssue]:
        return [i for i in self.issues if i.severity == GateSeverity.WARNING]

    def to_dict(self) -> dict:
        return {
            "gate": self.gate_name,
            "passed": self.passed,
            "blocking": self.blocking,
            "issues_count": len(self.issues),
            "critical": len(self.critical_issues),
            "errors": len(self.error_issues),
            "warnings": len(self.warning_issues),
            "auto_fixed": self.auto_fixed_count,
            "execution_time": self.execution_time_seconds,
        }

    def summary(self) -> str:
        """Краткая сводка"""
        status = "✅ PASSED" if self.passed else "❌ FAILED"
        parts = [f"{self.gate_name}: {status}"]

        if self.issues:
            parts.append(f"  Issues: {len(self.critical_issues)} critical, "
                        f"{len(self.error_issues)} errors, "
                        f"{len(self.warning_issues)} warnings")

        if self.auto_fixed_count > 0:
            parts.append(f"  Auto-fixed: {self.auto_fixed_count}")

        parts.append(f"  Time: {self.execution_time_seconds:.1f}s")

        return "\n".join(parts)


class QualityGate(ABC):
    """
    Базовый класс для quality gate

    Каждый gate должен реализовать:
    - check(): Проверка
    - fix() (опционально): Автоматическое исправление
    """

    def __init__(
        self,
        name: str,
        blocking: bool = True,
        auto_fix: bool = False
    ):
        self.name = name
        self.blocking = blocking
        self.auto_fix = auto_fix

    @abstractmethod
    async def check(self, context: Dict[str, Any]) -> GateResult:
        """
        Выполнить проверку

        Args:
            context: Контекст проверки (files, project_path, etc.)

        Returns:
            GateResult
        """
        pass

    async def fix(self, context: Dict[str, Any], issues: List[GateIssue]) -> int:
        """
        Попытаться автоматически исправить проблемы

        Args:
            context: Контекст
            issues: Список проблем для исправления

        Returns:
            Количество исправленных проблем
        """
        return 0  # По умолчанию — ничего не исправляем

    async def check_and_fix(self, context: Dict[str, Any]) -> GateResult:
        """
        Проверить и попытаться исправить

        Returns:
            GateResult после исправлений
        """
        # Первая проверка
        result = await self.check(context)

        # Если есть проблемы и включён auto_fix
        if not result.passed and self.auto_fix:
            fixable = [i for i in result.issues if i.auto_fixable]

            if fixable:
                fixed_count = await self.fix(context, fixable)
                result.auto_fixed_count = fixed_count

                # Повторная проверка
                if fixed_count > 0:
                    result = await self.check(context)
                    result.auto_fixed_count = fixed_count

        return result
