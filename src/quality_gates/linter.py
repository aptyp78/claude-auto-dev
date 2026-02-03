"""
Linter Gate

Проверка стиля кода с автоматическим исправлением.
Поддерживает: ruff, eslint, golangci-lint
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import subprocess

from .base import QualityGate, GateResult, GateIssue, GateSeverity


class LinterGate(QualityGate):
    """
    Gate для линтинга кода

    Поддерживает auto-fix для большинства проблем.
    """

    LINTER_COMMANDS = {
        "python": {
            "check": "ruff check .",
            "fix": "ruff check --fix .",
            "format_check": "ruff format --check .",
            "format": "ruff format .",
        },
        "javascript": {
            "check": "npx eslint .",
            "fix": "npx eslint --fix .",
        },
        "typescript": {
            "check": "npx eslint . --ext .ts,.tsx",
            "fix": "npx eslint --fix . --ext .ts,.tsx",
        },
        "go": {
            "check": "golangci-lint run",
            "fix": "golangci-lint run --fix",
        },
    }

    # Маппинг severity из разных линтеров
    SEVERITY_MAP = {
        # ruff
        "E": GateSeverity.ERROR,     # Error
        "W": GateSeverity.WARNING,   # Warning
        "F": GateSeverity.ERROR,     # Pyflakes
        "C": GateSeverity.WARNING,   # Convention
        "I": GateSeverity.INFO,      # Import
        # eslint
        "error": GateSeverity.ERROR,
        "warning": GateSeverity.WARNING,
        # golangci-lint
        "err": GateSeverity.ERROR,
        "warn": GateSeverity.WARNING,
    }

    def __init__(
        self,
        blocking: bool = True,
        auto_fix: bool = True,
        ignore_warnings: bool = False
    ):
        super().__init__("Linter", blocking=blocking, auto_fix=auto_fix)
        self.ignore_warnings = ignore_warnings

    def _detect_language(self, project_path: Path) -> Optional[str]:
        """Определить язык проекта"""
        if (project_path / "pyproject.toml").exists() or \
           (project_path / "requirements.txt").exists():
            return "python"

        if (project_path / "tsconfig.json").exists():
            return "typescript"

        if (project_path / "package.json").exists():
            return "javascript"

        if (project_path / "go.mod").exists():
            return "go"

        return None

    def _parse_ruff_output(self, output: str) -> List[GateIssue]:
        """Парсинг вывода ruff"""
        issues = []

        # Формат: file.py:10:5: E501 Line too long
        pattern = r"([^:]+):(\d+):(\d+):\s+([A-Z]\d+)\s+(.+)"

        for line in output.split("\n"):
            match = re.match(pattern, line.strip())
            if match:
                file_path, line_num, col, code, message = match.groups()

                # Определить severity по первой букве кода
                severity_key = code[0] if code else "E"
                severity = self.SEVERITY_MAP.get(severity_key, GateSeverity.WARNING)

                issues.append(GateIssue(
                    severity=severity,
                    message=message,
                    file=file_path,
                    line=int(line_num),
                    code=code,
                    auto_fixable=code.startswith(("I", "F401", "F841")),
                ))

        return issues

    def _parse_eslint_output(self, output: str) -> List[GateIssue]:
        """Парсинг вывода eslint (JSON format)"""
        issues = []

        try:
            # Попробуем JSON формат
            data = json.loads(output)
            for file_result in data:
                file_path = file_result.get("filePath", "")
                for msg in file_result.get("messages", []):
                    severity_str = "error" if msg.get("severity", 2) == 2 else "warning"
                    severity = self.SEVERITY_MAP.get(severity_str, GateSeverity.WARNING)

                    issues.append(GateIssue(
                        severity=severity,
                        message=msg.get("message", ""),
                        file=file_path,
                        line=msg.get("line"),
                        code=msg.get("ruleId"),
                        auto_fixable=msg.get("fix") is not None,
                    ))
        except json.JSONDecodeError:
            # Текстовый формат
            pattern = r"([^:]+):(\d+):(\d+):\s+(error|warning)\s+(.+?)\s+(\S+)$"
            for line in output.split("\n"):
                match = re.match(pattern, line.strip())
                if match:
                    file_path, line_num, col, severity_str, message, rule = match.groups()
                    severity = self.SEVERITY_MAP.get(severity_str, GateSeverity.WARNING)

                    issues.append(GateIssue(
                        severity=severity,
                        message=message,
                        file=file_path,
                        line=int(line_num),
                        code=rule,
                        auto_fixable=True,
                    ))

        return issues

    def _parse_golangci_output(self, output: str) -> List[GateIssue]:
        """Парсинг вывода golangci-lint"""
        issues = []

        # Формат: file.go:10:5: message (linter)
        pattern = r"([^:]+):(\d+):(\d+):\s+(.+?)\s+\((\w+)\)"

        for line in output.split("\n"):
            match = re.match(pattern, line.strip())
            if match:
                file_path, line_num, col, message, linter = match.groups()

                issues.append(GateIssue(
                    severity=GateSeverity.ERROR,
                    message=message,
                    file=file_path,
                    line=int(line_num),
                    code=linter,
                    auto_fixable=linter in ["gofmt", "goimports"],
                ))

        return issues

    async def _run_command(
        self,
        command: str,
        project_path: Path,
        timeout: int = 120
    ) -> tuple:
        """Запустить команду"""
        try:
            result = await asyncio.create_subprocess_shell(
                command,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            stdout, _ = await asyncio.wait_for(
                result.communicate(),
                timeout=timeout
            )

            return result.returncode, stdout.decode("utf-8", errors="replace")

        except asyncio.TimeoutError:
            return -1, f"Timeout after {timeout}s"
        except Exception as e:
            return -1, str(e)

    async def check(self, context: Dict[str, Any]) -> GateResult:
        """Запустить линтер"""
        start_time = time.time()

        project_path = Path(context.get("project_path", "."))
        language = context.get("language") or self._detect_language(project_path)

        if not language or language not in self.LINTER_COMMANDS:
            return GateResult(
                gate_name=self.name,
                passed=True,
                blocking=self.blocking,
                output="No linter configured for this project",
                execution_time_seconds=time.time() - start_time,
            )

        commands = self.LINTER_COMMANDS[language]
        command = commands.get("check", "")

        # Для eslint добавляем JSON формат
        if language in ["javascript", "typescript"]:
            command += " -f json"

        # Запустить линтер
        return_code, output = await self._run_command(command, project_path)

        # Парсинг результатов
        issues = []
        if language == "python":
            issues = self._parse_ruff_output(output)
        elif language in ["javascript", "typescript"]:
            issues = self._parse_eslint_output(output)
        elif language == "go":
            issues = self._parse_golangci_output(output)

        # Фильтрация по severity
        if self.ignore_warnings:
            issues = [i for i in issues if i.severity != GateSeverity.WARNING]

        # Определить passed
        errors = [i for i in issues if i.severity in [GateSeverity.ERROR, GateSeverity.CRITICAL]]
        passed = len(errors) == 0

        return GateResult(
            gate_name=self.name,
            passed=passed,
            blocking=self.blocking,
            issues=issues,
            total_checks=len(issues),
            failed_checks=len(errors),
            output=output if not passed else "",
            execution_time_seconds=time.time() - start_time,
        )

    async def fix(self, context: Dict[str, Any], issues: List[GateIssue]) -> int:
        """Автоматически исправить проблемы"""
        project_path = Path(context.get("project_path", "."))
        language = context.get("language") or self._detect_language(project_path)

        if not language or language not in self.LINTER_COMMANDS:
            return 0

        commands = self.LINTER_COMMANDS[language]

        # Запустить fix
        fix_command = commands.get("fix")
        if fix_command:
            return_code, output = await self._run_command(fix_command, project_path)

            # Для Python также запустить formatter
            if language == "python" and "format" in commands:
                await self._run_command(commands["format"], project_path)

            # Посчитать исправленные
            if return_code == 0:
                return len([i for i in issues if i.auto_fixable])

        return 0


# CLI для тестирования
if __name__ == "__main__":
    import sys

    async def main():
        gate = LinterGate(auto_fix=True)
        project_path = sys.argv[1] if len(sys.argv) > 1 else "."

        result = await gate.check_and_fix({"project_path": project_path})
        print(result.summary())

        if result.issues:
            print("\nRemaining issues:")
            for issue in result.issues[:10]:
                print(f"  [{issue.code}] {issue.file}:{issue.line} - {issue.message}")

    asyncio.run(main())
