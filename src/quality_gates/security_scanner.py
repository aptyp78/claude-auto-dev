"""
Security Scanner Gate

Сканирование на уязвимости и секреты.
Поддерживает: bandit (Python), npm audit, gosec, gitleaks
"""

import asyncio
import json
import re
import time
from pathlib import Path
from typing import Dict, Any, List, Optional

from .base import QualityGate, GateResult, GateIssue, GateSeverity


class SecurityScannerGate(QualityGate):
    """
    Gate для проверки безопасности

    Проверяет:
    - Уязвимости в коде (bandit, gosec)
    - Уязвимости в зависимостях (npm audit, pip-audit)
    - Захардкоженные секреты (gitleaks patterns)
    """

    # Паттерны для поиска секретов
    SECRET_PATTERNS = [
        (r'(?i)(api[_-]?key|apikey)\s*[=:]\s*["\']([^"\']+)["\']', "API Key"),
        (r'(?i)(secret|password|passwd|pwd)\s*[=:]\s*["\']([^"\']+)["\']', "Secret/Password"),
        (r'(?i)(token|auth[_-]?token)\s*[=:]\s*["\']([^"\']+)["\']', "Token"),
        (r'(?i)(aws[_-]?access[_-]?key[_-]?id)\s*[=:]\s*["\']([A-Z0-9]{20})["\']', "AWS Key"),
        (r'(?i)(private[_-]?key)\s*[=:]\s*["\']([^"\']+)["\']', "Private Key"),
        (r'-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----', "Private Key Block"),
        (r'(?i)bearer\s+[a-zA-Z0-9_\-\.]+', "Bearer Token"),
    ]

    # Файлы для игнорирования
    IGNORE_FILES = {
        ".env.example", ".env.sample", ".env.template",
        "requirements.txt", "package-lock.json", "yarn.lock",
        "*.md", "*.txt", "*.rst",
        # Игнорировать сам сканер и конфигурации
        "security_scanner.py",
        "models.yaml", "config.yaml", "settings.yaml",
    }

    SECURITY_COMMANDS = {
        "python": {
            "code": "bandit -r . -f json",
            "deps": "pip-audit --format json",
        },
        "javascript": {
            "deps": "npm audit --json",
        },
        "typescript": {
            "deps": "npm audit --json",
        },
        "go": {
            "code": "gosec -fmt=json ./...",
        },
    }

    def __init__(
        self,
        blocking: bool = True,
        scan_secrets: bool = True,
        min_severity: str = "medium"
    ):
        super().__init__("Security Scanner", blocking=blocking, auto_fix=False)
        self.scan_secrets = scan_secrets
        self.min_severity = min_severity

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

    def _should_scan_file(self, file_path: Path) -> bool:
        """Проверить, нужно ли сканировать файл"""
        name = file_path.name

        # Игнорируем по имени
        for pattern in self.IGNORE_FILES:
            if pattern.startswith("*"):
                if name.endswith(pattern[1:]):
                    return False
            elif name == pattern:
                return False

        # Игнорируем бинарные файлы
        binary_extensions = {".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin"}
        if file_path.suffix in binary_extensions:
            return False

        # Игнорируем node_modules, .git, etc.
        path_str = str(file_path)
        ignore_dirs = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build"}
        for ignore_dir in ignore_dirs:
            if f"/{ignore_dir}/" in path_str or path_str.startswith(f"{ignore_dir}/"):
                return False

        return True

    def _scan_file_for_secrets(self, file_path: Path) -> List[GateIssue]:
        """Сканировать файл на наличие секретов"""
        issues = []

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except:
            return issues

        for line_num, line in enumerate(content.split("\n"), 1):
            for pattern, secret_type in self.SECRET_PATTERNS:
                if re.search(pattern, line):
                    # Проверяем, не является ли это примером или плейсхолдером
                    lower_line = line.lower()
                    if any(placeholder in lower_line for placeholder in
                          ["example", "placeholder", "your_", "xxx", "changeme", "<", ">"]):
                        continue

                    issues.append(GateIssue(
                        severity=GateSeverity.CRITICAL,
                        message=f"Potential {secret_type} found",
                        file=str(file_path),
                        line=line_num,
                        code="SECRET_DETECTED",
                        suggestion="Use environment variables or a secrets manager",
                    ))

        return issues

    def _scan_directory_for_secrets(self, project_path: Path) -> List[GateIssue]:
        """Сканировать директорию на секреты"""
        issues = []

        # Типы файлов для сканирования
        scan_extensions = {
            ".py", ".js", ".ts", ".jsx", ".tsx", ".go",
            ".java", ".rb", ".php", ".cs", ".swift",
            ".yml", ".yaml", ".json", ".xml", ".ini", ".cfg",
            ".env", ".sh", ".bash",
        }

        for file_path in project_path.rglob("*"):
            if not file_path.is_file():
                continue

            if file_path.suffix not in scan_extensions:
                continue

            if not self._should_scan_file(file_path):
                continue

            file_issues = self._scan_file_for_secrets(file_path)
            issues.extend(file_issues)

        return issues

    def _parse_bandit_output(self, output: str) -> List[GateIssue]:
        """Парсинг вывода bandit"""
        issues = []

        try:
            data = json.loads(output)
            for result in data.get("results", []):
                severity_map = {
                    "HIGH": GateSeverity.CRITICAL,
                    "MEDIUM": GateSeverity.ERROR,
                    "LOW": GateSeverity.WARNING,
                }

                severity = severity_map.get(
                    result.get("issue_severity", "LOW"),
                    GateSeverity.WARNING
                )

                # Фильтр по min_severity
                if self.min_severity == "high" and severity not in [GateSeverity.CRITICAL]:
                    continue
                if self.min_severity == "medium" and severity == GateSeverity.WARNING:
                    continue

                issues.append(GateIssue(
                    severity=severity,
                    message=result.get("issue_text", ""),
                    file=result.get("filename", ""),
                    line=result.get("line_number"),
                    code=result.get("test_id"),
                    suggestion=result.get("more_info"),
                ))

        except json.JSONDecodeError:
            pass

        return issues

    def _parse_npm_audit_output(self, output: str) -> List[GateIssue]:
        """Парсинг вывода npm audit"""
        issues = []

        try:
            data = json.loads(output)

            # npm audit v7+ format
            vulnerabilities = data.get("vulnerabilities", {})
            for name, vuln in vulnerabilities.items():
                severity_map = {
                    "critical": GateSeverity.CRITICAL,
                    "high": GateSeverity.CRITICAL,
                    "moderate": GateSeverity.ERROR,
                    "low": GateSeverity.WARNING,
                }

                severity = severity_map.get(
                    vuln.get("severity", "low"),
                    GateSeverity.WARNING
                )

                # Фильтр по min_severity
                if self.min_severity == "high" and severity not in [GateSeverity.CRITICAL]:
                    continue
                if self.min_severity == "medium" and severity == GateSeverity.WARNING:
                    continue

                issues.append(GateIssue(
                    severity=severity,
                    message=f"Vulnerability in {name}: {vuln.get('severity')}",
                    code=f"NPM_VULN_{vuln.get('severity', 'unknown').upper()}",
                    suggestion=f"Run 'npm audit fix' or update {name}",
                ))

        except json.JSONDecodeError:
            pass

        return issues

    def _parse_gosec_output(self, output: str) -> List[GateIssue]:
        """Парсинг вывода gosec"""
        issues = []

        try:
            data = json.loads(output)
            for result in data.get("Issues", []):
                severity_map = {
                    "HIGH": GateSeverity.CRITICAL,
                    "MEDIUM": GateSeverity.ERROR,
                    "LOW": GateSeverity.WARNING,
                }

                severity = severity_map.get(
                    result.get("severity", "LOW"),
                    GateSeverity.WARNING
                )

                issues.append(GateIssue(
                    severity=severity,
                    message=result.get("details", ""),
                    file=result.get("file", ""),
                    line=result.get("line"),
                    code=result.get("rule_id"),
                ))

        except json.JSONDecodeError:
            pass

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
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                result.communicate(),
                timeout=timeout
            )

            return result.returncode, stdout.decode("utf-8", errors="replace")

        except asyncio.TimeoutError:
            return -1, f"Timeout after {timeout}s"
        except Exception as e:
            return -1, str(e)

    async def check(self, context: Dict[str, Any]) -> GateResult:
        """Запустить сканирование безопасности"""
        start_time = time.time()

        project_path = Path(context.get("project_path", "."))
        language = context.get("language") or self._detect_language(project_path)

        all_issues = []

        # 1. Сканирование на секреты
        if self.scan_secrets:
            secret_issues = self._scan_directory_for_secrets(project_path)
            all_issues.extend(secret_issues)

        # 2. Сканирование кода (если есть инструмент)
        if language and language in self.SECURITY_COMMANDS:
            commands = self.SECURITY_COMMANDS[language]

            # Code scanner
            if "code" in commands:
                return_code, output = await self._run_command(
                    commands["code"],
                    project_path
                )

                if return_code >= 0:  # Даже при найденных проблемах код 0 или 1
                    if language == "python":
                        all_issues.extend(self._parse_bandit_output(output))
                    elif language == "go":
                        all_issues.extend(self._parse_gosec_output(output))

            # Dependency scanner
            if "deps" in commands:
                return_code, output = await self._run_command(
                    commands["deps"],
                    project_path
                )

                if language in ["javascript", "typescript"]:
                    all_issues.extend(self._parse_npm_audit_output(output))

        # Определить passed
        critical = [i for i in all_issues if i.severity == GateSeverity.CRITICAL]
        errors = [i for i in all_issues if i.severity == GateSeverity.ERROR]

        # Critical всегда блокирует
        passed = len(critical) == 0

        return GateResult(
            gate_name=self.name,
            passed=passed,
            blocking=self.blocking,
            issues=all_issues,
            total_checks=len(all_issues),
            failed_checks=len(critical) + len(errors),
            execution_time_seconds=time.time() - start_time,
        )


# CLI для тестирования
if __name__ == "__main__":
    import sys

    async def main():
        gate = SecurityScannerGate(scan_secrets=True)
        project_path = sys.argv[1] if len(sys.argv) > 1 else "."

        result = await gate.check({"project_path": project_path})
        print(result.summary())

        if result.issues:
            print("\nSecurity issues:")
            for issue in result.issues[:10]:
                print(f"  [{issue.severity.value}] {issue.file}:{issue.line} - {issue.message}")

    asyncio.run(main())
