"""
Test Runner Gate

Запускает тесты и проверяет результаты.
Поддерживает: pytest, vitest, jest, go test
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
import subprocess

from .base import QualityGate, GateResult, GateIssue, GateSeverity


class TestRunnerGate(QualityGate):
    """
    Gate для запуска тестов

    Определяет тестовый фреймворк автоматически по проекту.
    """

    # Маппинг языков на команды тестов
    TEST_COMMANDS = {
        "python": {
            "detect": ["pytest.ini", "pyproject.toml", "setup.py", "conftest.py"],
            "command": "pytest -v --tb=short",
            "parallel": "pytest -v --tb=short -n auto",
        },
        "javascript": {
            "detect": ["package.json"],
            "command": "npm test",
            "vitest": "npx vitest run",
            "jest": "npx jest",
        },
        "typescript": {
            "detect": ["package.json", "tsconfig.json"],
            "command": "npm test",
            "vitest": "npx vitest run",
            "jest": "npx jest",
        },
        "go": {
            "detect": ["go.mod"],
            "command": "go test ./...",
            "verbose": "go test -v ./...",
        },
    }

    def __init__(
        self,
        blocking: bool = True,
        parallel: bool = True,
        timeout: int = 300
    ):
        super().__init__("Test Runner", blocking=blocking, auto_fix=False)
        self.parallel = parallel
        self.timeout = timeout

    def _detect_language(self, project_path: Path) -> Optional[str]:
        """Определить язык проекта"""
        for lang, config in self.TEST_COMMANDS.items():
            for detect_file in config["detect"]:
                if (project_path / detect_file).exists():
                    return lang
        return None

    def _detect_test_framework(self, project_path: Path, language: str) -> str:
        """Определить тестовый фреймворк"""
        if language in ["javascript", "typescript"]:
            package_json = project_path / "package.json"
            if package_json.exists():
                try:
                    with open(package_json) as f:
                        pkg = json.load(f)

                    deps = {
                        **pkg.get("dependencies", {}),
                        **pkg.get("devDependencies", {})
                    }

                    if "vitest" in deps:
                        return "vitest"
                    if "jest" in deps:
                        return "jest"
                except:
                    pass

        return "default"

    def _get_test_command(
        self,
        project_path: Path,
        language: str,
        framework: str
    ) -> str:
        """Получить команду для запуска тестов"""
        config = self.TEST_COMMANDS.get(language, {})

        if framework in config:
            return config[framework]

        if self.parallel and "parallel" in config:
            return config["parallel"]

        return config.get("command", "echo 'No test command found'")

    def _parse_pytest_output(self, output: str) -> List[GateIssue]:
        """Парсинг вывода pytest"""
        issues = []

        # Ищем failed тесты
        failed_pattern = r"FAILED\s+(\S+)::(\S+)"
        for match in re.finditer(failed_pattern, output):
            file_path, test_name = match.groups()
            issues.append(GateIssue(
                severity=GateSeverity.ERROR,
                message=f"Test failed: {test_name}",
                file=file_path,
                code="TEST_FAILED",
            ))

        # Ищем errors
        error_pattern = r"ERROR\s+(\S+)"
        for match in re.finditer(error_pattern, output):
            issues.append(GateIssue(
                severity=GateSeverity.CRITICAL,
                message=f"Test error: {match.group(1)}",
                code="TEST_ERROR",
            ))

        return issues

    def _parse_vitest_output(self, output: str) -> List[GateIssue]:
        """Парсинг вывода vitest"""
        issues = []

        # Ищем failed тесты
        failed_pattern = r"FAIL\s+(\S+)"
        for match in re.finditer(failed_pattern, output):
            issues.append(GateIssue(
                severity=GateSeverity.ERROR,
                message=f"Test failed: {match.group(1)}",
                code="TEST_FAILED",
            ))

        return issues

    def _parse_go_output(self, output: str) -> List[GateIssue]:
        """Парсинг вывода go test"""
        issues = []

        # Ищем FAIL
        fail_pattern = r"--- FAIL:\s+(\S+)"
        for match in re.finditer(fail_pattern, output):
            issues.append(GateIssue(
                severity=GateSeverity.ERROR,
                message=f"Test failed: {match.group(1)}",
                code="TEST_FAILED",
            ))

        return issues

    def _extract_stats(self, output: str, language: str) -> Dict[str, int]:
        """Извлечь статистику тестов"""
        stats = {"passed": 0, "failed": 0, "skipped": 0, "total": 0}

        if language == "python":
            # pytest: "5 passed, 2 failed, 1 skipped"
            match = re.search(
                r"(\d+)\s+passed.*?(\d+)\s+failed.*?(\d+)\s+skipped",
                output
            )
            if match:
                stats["passed"] = int(match.group(1))
                stats["failed"] = int(match.group(2))
                stats["skipped"] = int(match.group(3))
            else:
                # Простой формат: "5 passed"
                passed = re.search(r"(\d+)\s+passed", output)
                failed = re.search(r"(\d+)\s+failed", output)
                if passed:
                    stats["passed"] = int(passed.group(1))
                if failed:
                    stats["failed"] = int(failed.group(1))

        elif language in ["javascript", "typescript"]:
            # vitest/jest: "Tests: 5 passed, 2 failed"
            passed = re.search(r"(\d+)\s+pass", output, re.IGNORECASE)
            failed = re.search(r"(\d+)\s+fail", output, re.IGNORECASE)
            if passed:
                stats["passed"] = int(passed.group(1))
            if failed:
                stats["failed"] = int(failed.group(1))

        elif language == "go":
            # go test: "ok" или "FAIL"
            ok_count = len(re.findall(r"^ok\s+", output, re.MULTILINE))
            fail_count = len(re.findall(r"^FAIL\s+", output, re.MULTILINE))
            stats["passed"] = ok_count
            stats["failed"] = fail_count

        stats["total"] = stats["passed"] + stats["failed"] + stats["skipped"]
        return stats

    async def check(self, context: Dict[str, Any]) -> GateResult:
        """Запустить тесты"""
        start_time = time.time()

        project_path = Path(context.get("project_path", "."))
        files_changed = context.get("files_changed", [])

        # Определить язык и фреймворк
        language = context.get("language") or self._detect_language(project_path)

        if not language:
            return GateResult(
                gate_name=self.name,
                passed=True,
                blocking=self.blocking,
                output="No test framework detected",
                execution_time_seconds=time.time() - start_time,
            )

        framework = self._detect_test_framework(project_path, language)
        command = self._get_test_command(project_path, language, framework)

        # Запустить тесты
        try:
            result = await asyncio.create_subprocess_shell(
                command,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            stdout, _ = await asyncio.wait_for(
                result.communicate(),
                timeout=self.timeout
            )

            output = stdout.decode("utf-8", errors="replace")
            return_code = result.returncode

        except asyncio.TimeoutError:
            return GateResult(
                gate_name=self.name,
                passed=False,
                blocking=self.blocking,
                error=f"Test timeout after {self.timeout}s",
                execution_time_seconds=time.time() - start_time,
            )

        except Exception as e:
            return GateResult(
                gate_name=self.name,
                passed=False,
                blocking=self.blocking,
                error=str(e),
                execution_time_seconds=time.time() - start_time,
            )

        # Парсинг результатов
        issues = []
        if language == "python":
            issues = self._parse_pytest_output(output)
        elif language in ["javascript", "typescript"]:
            issues = self._parse_vitest_output(output)
        elif language == "go":
            issues = self._parse_go_output(output)

        # Статистика
        stats = self._extract_stats(output, language)

        passed = return_code == 0 and stats["failed"] == 0

        return GateResult(
            gate_name=self.name,
            passed=passed,
            blocking=self.blocking,
            issues=issues,
            total_checks=stats["total"],
            passed_checks=stats["passed"],
            failed_checks=stats["failed"],
            output=output,
            execution_time_seconds=time.time() - start_time,
        )


# CLI для тестирования
if __name__ == "__main__":
    import sys

    async def main():
        gate = TestRunnerGate()
        project_path = sys.argv[1] if len(sys.argv) > 1 else "."

        result = await gate.check({"project_path": project_path})
        print(result.summary())

        if result.issues:
            print("\nIssues:")
            for issue in result.issues:
                print(f"  {issue.severity.value}: {issue.message}")

    asyncio.run(main())
