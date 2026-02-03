"""
Git Integration

Интеграция с Git для управления версиями.
"""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
from datetime import datetime

from .mcp_client import LocalMCPClient, MCPToolCall


@dataclass
class GitStatus:
    """Статус git репозитория"""
    branch: str = "main"
    is_clean: bool = True
    staged: List[str] = field(default_factory=list)
    modified: List[str] = field(default_factory=list)
    untracked: List[str] = field(default_factory=list)
    deleted: List[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.staged or self.modified or self.untracked or self.deleted)

    def summary(self) -> str:
        parts = [f"Branch: {self.branch}"]
        if self.staged:
            parts.append(f"Staged: {len(self.staged)}")
        if self.modified:
            parts.append(f"Modified: {len(self.modified)}")
        if self.untracked:
            parts.append(f"Untracked: {len(self.untracked)}")
        if self.deleted:
            parts.append(f"Deleted: {len(self.deleted)}")
        return " | ".join(parts)


@dataclass
class GitCommit:
    """Git коммит"""
    hash: str
    short_hash: str
    message: str
    author: str
    date: datetime
    files_changed: int = 0


@dataclass
class GitDiff:
    """Diff между версиями"""
    files: List[str] = field(default_factory=list)
    additions: int = 0
    deletions: int = 0
    raw: str = ""


class GitIntegration:
    """
    Интеграция с Git

    Предоставляет:
    - Статус репозитория
    - Управление коммитами
    - Diff и история
    - Ветки
    """

    def __init__(self, repo_path: Path):
        """
        Args:
            repo_path: Путь к репозиторию
        """
        self.repo_path = Path(repo_path)
        self.client = LocalMCPClient(self.repo_path)

    async def _run_git(
        self,
        *args: str,
        check: bool = True
    ) -> Tuple[int, str, str]:
        """Выполнить git команду"""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=str(self.repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode, stdout.decode(), stderr.decode()

    async def get_status(self) -> GitStatus:
        """Получить статус репозитория"""
        status = GitStatus()

        # Текущая ветка
        code, branch, _ = await self._run_git("branch", "--show-current")
        if code == 0:
            status.branch = branch.strip() or "HEAD"

        # Статус файлов
        code, output, _ = await self._run_git("status", "--porcelain")
        if code == 0:
            for line in output.strip().split("\n"):
                if not line:
                    continue

                status_code = line[:2]
                file_path = line[3:].strip()

                # Staged
                if status_code[0] in "MADRC":
                    status.staged.append(file_path)

                # Modified (unstaged)
                if status_code[1] == "M":
                    status.modified.append(file_path)

                # Untracked
                if status_code == "??":
                    status.untracked.append(file_path)

                # Deleted
                if status_code[1] == "D" or status_code[0] == "D":
                    status.deleted.append(file_path)

        status.is_clean = not status.has_changes
        return status

    async def get_diff(
        self,
        staged: bool = False,
        file_path: Optional[str] = None
    ) -> GitDiff:
        """
        Получить diff

        Args:
            staged: Staged изменения или unstaged
            file_path: Конкретный файл (опционально)
        """
        args = ["diff"]
        if staged:
            args.append("--staged")
        if file_path:
            args.extend(["--", file_path])

        code, output, _ = await self._run_git(*args)

        diff = GitDiff(raw=output)

        if code == 0 and output:
            # Парсим файлы и статистику
            diff.files = re.findall(r"^diff --git a/(.+?) b/", output, re.MULTILINE)
            diff.additions = len(re.findall(r"^\+[^+]", output, re.MULTILINE))
            diff.deletions = len(re.findall(r"^-[^-]", output, re.MULTILINE))

        return diff

    async def get_log(
        self,
        limit: int = 10,
        file_path: Optional[str] = None
    ) -> List[GitCommit]:
        """Получить историю коммитов"""
        args = [
            "log",
            f"-{limit}",
            "--format=%H|%h|%s|%an|%aI",
        ]
        if file_path:
            args.extend(["--", file_path])

        code, output, _ = await self._run_git(*args)
        commits = []

        if code == 0:
            for line in output.strip().split("\n"):
                if not line:
                    continue

                parts = line.split("|", 4)
                if len(parts) >= 5:
                    commits.append(GitCommit(
                        hash=parts[0],
                        short_hash=parts[1],
                        message=parts[2],
                        author=parts[3],
                        date=datetime.fromisoformat(parts[4]),
                    ))

        return commits

    async def stage_files(self, files: List[str]) -> bool:
        """Добавить файлы в staging"""
        if not files:
            return False

        code, _, _ = await self._run_git("add", *files)
        return code == 0

    async def stage_all(self) -> bool:
        """Добавить все изменения"""
        code, _, _ = await self._run_git("add", "-A")
        return code == 0

    async def unstage_files(self, files: List[str]) -> bool:
        """Убрать файлы из staging"""
        if not files:
            return False

        code, _, _ = await self._run_git("reset", "HEAD", *files)
        return code == 0

    async def commit(
        self,
        message: str,
        author: Optional[str] = None
    ) -> Optional[GitCommit]:
        """
        Создать коммит

        Args:
            message: Сообщение коммита
            author: Автор (опционально)

        Returns:
            GitCommit или None при ошибке
        """
        args = ["commit", "-m", message]
        if author:
            args.extend(["--author", author])

        code, output, stderr = await self._run_git(*args)

        if code == 0:
            # Получить созданный коммит
            logs = await self.get_log(limit=1)
            return logs[0] if logs else None

        return None

    async def create_branch(
        self,
        name: str,
        checkout: bool = True
    ) -> bool:
        """Создать ветку"""
        if checkout:
            code, _, _ = await self._run_git("checkout", "-b", name)
        else:
            code, _, _ = await self._run_git("branch", name)

        return code == 0

    async def checkout(
        self,
        ref: str,
        create: bool = False
    ) -> bool:
        """Переключить ветку"""
        args = ["checkout"]
        if create:
            args.append("-b")
        args.append(ref)

        code, _, _ = await self._run_git(*args)
        return code == 0

    async def get_branches(
        self,
        remote: bool = False
    ) -> List[str]:
        """Список веток"""
        args = ["branch"]
        if remote:
            args.append("-a")

        code, output, _ = await self._run_git(*args)

        branches = []
        if code == 0:
            for line in output.strip().split("\n"):
                branch = line.strip()
                if branch.startswith("*"):
                    branch = branch[2:]
                if branch:
                    branches.append(branch)

        return branches

    async def get_current_branch(self) -> str:
        """Текущая ветка"""
        code, output, _ = await self._run_git("branch", "--show-current")
        if code == 0 and output.strip():
            return output.strip()
        return "HEAD"

    async def stash(self, message: Optional[str] = None) -> bool:
        """Сохранить изменения в stash"""
        args = ["stash", "push"]
        if message:
            args.extend(["-m", message])

        code, _, _ = await self._run_git(*args)
        return code == 0

    async def stash_pop(self) -> bool:
        """Восстановить из stash"""
        code, _, _ = await self._run_git("stash", "pop")
        return code == 0

    async def get_changed_files(
        self,
        base_ref: str = "HEAD~1"
    ) -> List[str]:
        """Получить список изменённых файлов относительно ref"""
        code, output, _ = await self._run_git(
            "diff", "--name-only", base_ref, "HEAD"
        )

        if code == 0:
            return [f.strip() for f in output.strip().split("\n") if f.strip()]

        return []

    async def reset(
        self,
        ref: str = "HEAD",
        mode: str = "mixed"  # soft, mixed, hard
    ) -> bool:
        """Reset к ref"""
        code, _, _ = await self._run_git("reset", f"--{mode}", ref)
        return code == 0

    async def show_commit(self, ref: str = "HEAD") -> str:
        """Показать содержимое коммита"""
        code, output, _ = await self._run_git("show", ref, "--stat")
        return output if code == 0 else ""

    # Утилиты для автоматизации

    async def auto_commit_if_changed(
        self,
        message: str,
        files: Optional[List[str]] = None
    ) -> Optional[GitCommit]:
        """
        Автоматически создать коммит если есть изменения

        Args:
            message: Сообщение коммита
            files: Список файлов (None = все)

        Returns:
            GitCommit или None
        """
        status = await self.get_status()

        if not status.has_changes:
            return None

        if files:
            await self.stage_files(files)
        else:
            await self.stage_all()

        return await self.commit(message)

    async def create_feature_branch(
        self,
        feature_name: str
    ) -> bool:
        """Создать feature branch"""
        branch_name = f"feature/{feature_name}"
        return await self.create_branch(branch_name, checkout=True)

    async def get_uncommitted_changes_summary(self) -> str:
        """Краткая сводка незакоммиченных изменений"""
        status = await self.get_status()

        if status.is_clean:
            return "Working tree clean"

        parts = []
        if status.staged:
            parts.append(f"{len(status.staged)} staged")
        if status.modified:
            parts.append(f"{len(status.modified)} modified")
        if status.untracked:
            parts.append(f"{len(status.untracked)} untracked")

        return ", ".join(parts)
