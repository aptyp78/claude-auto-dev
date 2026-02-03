"""
Coverage Checker Gate

Проверка покрытия тестами.
Поддерживает: pytest-cov, c8/istanbul, go test -cover
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from .base import QualityGate, GateResult, GateIssue, GateSeverity


class CoverageCheckerGate(QualityGate):
    """
    Gate для проверки покрытия кода тестами

    Пороговые значения:
    - critical: 90% (критический код)
    - normal: 70% (обычный код)
    - minimum: 50% (минимально допустимый)
    """

    COVERAGE_COMMANDS = {
        "python": {
            "command": "pytest --cov=. --cov-report=json --cov-report=term -q",
            "report_file": "coverage.json",
        },
        "javascript": {
            "command": "npx vitest run --coverage --reporter=json",
            "report_file": "coverage/coverage-final.json",
        },
        "typescript": {
            "command": "npx vitest run --coverage --reporter=json",
            "report_file": "coverage/coverage-final.json",
        },
        "go": {
            "command": "go test -coverprofile=coverage.out ./... && go tool cover -func=coverage.out",
            "report_file": "coverage.out",
        },
    }

    # Критичные директории/файлы требуют высокого покрытия
    CRITICAL_PATTERNS = [
        r"auth", r"security", r"payment", r"billing",
        r"api", r"handler", r"controller", r"service",
    ]

    def __init__(
        self,
        blocking: bool = False,  # По умолчанию не блокирует
        min_coverage: float = 70.0,
        critical_coverage: float = 90.0
    ):
        super().__init__("Coverage Checker", blocking=blocking, auto_fix=False)
        self.min_coverage = min_coverage
        self.critical_coverage = critical_coverage

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

    def _is_critical_file(self, file_path: str) -> bool:
        """Проверить, является ли файл критичным"""
        lower_path = file_path.lower()
        return any(re.search(pattern, lower_path) for pattern in self.CRITICAL_PATTERNS)

    def _parse_python_coverage(
        self,
        project_path: Path,
        output: str
    ) -> tuple:
        """Парсинг coverage для Python"""
        issues = []
        total_coverage = 0.0
        file_coverages = {}

        # Попробуем прочитать JSON отчёт
        report_file = project_path / "coverage.json"
        if report_file.exists():
            try:
                with open(report_file) as f:
                    data = json.load(f)

                total_coverage = data.get("totals", {}).get("percent_covered", 0)

                for file_path, file_data in data.get("files", {}).items():
                    coverage = file_data.get("summary", {}).get("percent_covered", 0)
                    file_coverages[file_path] = coverage

                    # Проверка порогов
                    threshold = self.critical_coverage if self._is_critical_file(file_path) else self.min_coverage

                    if coverage < threshold:
                        severity = GateSeverity.ERROR if self._is_critical_file(file_path) else GateSeverity.WARNING
                        issues.append(GateIssue(
                            severity=severity,
                            message=f"Coverage {coverage:.1f}% below threshold {threshold}%",
                            file=file_path,
                            code="LOW_COVERAGE",
                            suggestion=f"Add tests to improve coverage to at least {threshold}%",
                        ))

            except (json.JSONDecodeError, IOError):
                pass

        # Fallback: парсим текстовый вывод
        if total_coverage == 0:
            match = re.search(r"TOTAL\s+\d+\s+\d+\s+(\d+)%", output)
            if match:
                total_coverage = float(match.group(1))

        return total_coverage, file_coverages, issues

    def _parse_js_coverage(
        self,
        project_path: Path,
        output: str
    ) -> tuple:
        """Парсинг coverage для JavaScript/TypeScript"""
        issues = []
        total_coverage = 0.0
        file_coverages = {}

        # Читаем JSON отчёт
        report_file = project_path / "coverage" / "coverage-final.json"
        if report_file.exists():
            try:
                with open(report_file) as f:
                    data = json.load(f)

                total_statements = 0
                covered_statements = 0

                for file_path, file_data in data.items():
                    s = file_data.get("s", {})  # statements
                    file_total = len(s)
                    file_covered = sum(1 for v in s.values() if v > 0)

                    total_statements += file_total
                    covered_statements += file_covered

                    coverage = (file_covered / file_total * 100) if file_total > 0 else 0
                    file_coverages[file_path] = coverage

                    threshold = self.critical_coverage if self._is_critical_file(file_path) else self.min_coverage

                    if coverage < threshold:
                        severity = GateSeverity.ERROR if self._is_critical_file(file_path) else GateSeverity.WARNING
                        issues.append(GateIssue(
                            severity=severity,
                            message=f"Coverage {coverage:.1f}% below threshold {threshold}%",
                            file=file_path,
                            code="LOW_COVERAGE",
                        ))

                total_coverage = (covered_statements / total_statements * 100) if total_statements > 0 else 0

            except (json.JSONDecodeError, IOError):
                pass

        return total_coverage, file_coverages, issues

    def _parse_go_coverage(
        self,
        project_path: Path,
        output: str
    ) -> tuple:
        """Парсинг coverage для Go"""
        issues = []
        file_coverages = {}
        total_coverage = 0.0

        # Парсим вывод go tool cover -func
        # Формат: github.com/user/pkg/file.go:10:	FuncName	75.0%
        for line in output.split("\n"):
            match = re.match(r"(\S+):\d+:\s+\S+\s+(\d+\.?\d*)%", line)
            if match:
                file_path, coverage_str = match.groups()
                coverage = float(coverage_str)

                # Сохраняем максимальное покрытие для файла
                if file_path not in file_coverages or coverage > file_coverages[file_path]:
                    file_coverages[file_path] = coverage

        # Общее покрытие — последняя строка
        total_match = re.search(r"total:\s+\(statements\)\s+(\d+\.?\d*)%", output)
        if total_match:
            total_coverage = float(total_match.group(1))

        # Проверка порогов
        for file_path, coverage in file_coverages.items():
            threshold = self.critical_coverage if self._is_critical_file(file_path) else self.min_coverage

            if coverage < threshold:
                severity = GateSeverity.ERROR if self._is_critical_file(file_path) else GateSeverity.WARNING
                issues.append(GateIssue(
                    severity=severity,
                    message=f"Coverage {coverage:.1f}% below threshold {threshold}%",
                    file=file_path,
                    code="LOW_COVERAGE",
                ))

        return total_coverage, file_coverages, issues

    async def _run_command(
        self,
        command: str,
        project_path: Path,
        timeout: int = 300
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
        """Проверить покрытие"""
        start_time = time.time()

        project_path = Path(context.get("project_path", "."))
        language = context.get("language") or self._detect_language(project_path)

        if not language or language not in self.COVERAGE_COMMANDS:
            return GateResult(
                gate_name=self.name,
                passed=True,
                blocking=self.blocking,
                output="No coverage tool configured for this project",
                execution_time_seconds=time.time() - start_time,
            )

        config = self.COVERAGE_COMMANDS[language]
        command = config["command"]

        # Запустить тесты с coverage
        return_code, output = await self._run_command(command, project_path)

        # Парсинг результатов
        total_coverage = 0.0
        file_coverages = {}
        issues = []

        if language == "python":
            total_coverage, file_coverages, issues = self._parse_python_coverage(project_path, output)
        elif language in ["javascript", "typescript"]:
            total_coverage, file_coverages, issues = self._parse_js_coverage(project_path, output)
        elif language == "go":
            total_coverage, file_coverages, issues = self._parse_go_coverage(project_path, output)

        # Общая проверка порога
        if total_coverage < self.min_coverage:
            issues.insert(0, GateIssue(
                severity=GateSeverity.ERROR,
                message=f"Total coverage {total_coverage:.1f}% below minimum {self.min_coverage}%",
                code="TOTAL_COVERAGE_LOW",
            ))

        # Определить passed
        passed = total_coverage >= self.min_coverage

        return GateResult(
            gate_name=self.name,
            passed=passed,
            blocking=self.blocking,
            issues=issues,
            total_checks=len(file_coverages),
            passed_checks=sum(1 for c in file_coverages.values() if c >= self.min_coverage),
            failed_checks=sum(1 for c in file_coverages.values() if c < self.min_coverage),
            output=f"Total coverage: {total_coverage:.1f}%",
            execution_time_seconds=time.time() - start_time,
        )


# CLI для тестирования
if __name__ == "__main__":
    import sys

    async def main():
        gate = CoverageCheckerGate(min_coverage=70, critical_coverage=90)
        project_path = sys.argv[1] if len(sys.argv) > 1 else "."

        result = await gate.check({"project_path": project_path})
        print(result.summary())

        if result.issues:
            print("\nCoverage issues:")
            for issue in result.issues[:10]:
                print(f"  {issue.file}: {issue.message}")

    asyncio.run(main())
