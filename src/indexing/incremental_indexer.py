"""
Incremental Indexer для Code RAG.

Git-aware индексация:
1. Отслеживает изменения через git
2. Переиндексирует только измененные файлы
3. Удаляет устаревшие чанки
4. Поддерживает консистентность индекса
"""

import asyncio
import hashlib
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional
import json

from qdrant_client import QdrantClient, models


class ChangeType(Enum):
    """Тип изменения файла."""
    ADDED = "A"
    MODIFIED = "M"
    DELETED = "D"
    RENAMED = "R"
    COPIED = "C"


@dataclass
class FileChange:
    """Изменение файла."""
    path: str
    change_type: ChangeType
    old_path: Optional[str] = None  # Для renamed
    content_hash: Optional[str] = None


@dataclass
class IndexState:
    """Состояние индекса."""
    git_commit: str
    indexed_files: dict[str, str]  # path -> content_hash
    last_updated: datetime
    total_chunks: int
    total_files: int

    def to_dict(self) -> dict:
        return {
            "git_commit": self.git_commit,
            "indexed_files": self.indexed_files,
            "last_updated": self.last_updated.isoformat(),
            "total_chunks": self.total_chunks,
            "total_files": self.total_files,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IndexState":
        return cls(
            git_commit=data["git_commit"],
            indexed_files=data["indexed_files"],
            last_updated=datetime.fromisoformat(data["last_updated"]),
            total_chunks=data["total_chunks"],
            total_files=data["total_files"],
        )


class GitChangeDetector:
    """
    Определяет изменения через git.

    Использует:
    - git diff для измененных файлов
    - git status для untracked
    - content hash для точной проверки
    """

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def get_current_commit(self) -> str:
        """Получает текущий commit hash."""
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def get_changes_since(self, commit: str) -> list[FileChange]:
        """
        Получает все изменения с указанного commit.

        Returns:
            Список FileChange
        """
        changes = []

        # git diff для tracked files
        result = subprocess.run(
            ["git", "diff", "--name-status", commit, "HEAD"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )

        for line in result.stdout.strip().split("\n"):
            if not line:
                continue

            parts = line.split("\t")
            status = parts[0][0]  # Первый символ статуса

            try:
                change_type = ChangeType(status)
            except ValueError:
                change_type = ChangeType.MODIFIED

            if change_type == ChangeType.RENAMED and len(parts) >= 3:
                changes.append(FileChange(
                    path=parts[2],
                    change_type=change_type,
                    old_path=parts[1],
                ))
            else:
                changes.append(FileChange(
                    path=parts[-1],
                    change_type=change_type,
                ))

        # Добавляем untracked files
        untracked = self._get_untracked_files()
        for path in untracked:
            changes.append(FileChange(
                path=path,
                change_type=ChangeType.ADDED,
            ))

        return changes

    def get_all_tracked_files(self, extensions: list[str] = None) -> list[str]:
        """
        Получает все tracked файлы.

        Args:
            extensions: Фильтр по расширениям [".py", ".js"]
        """
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )

        files = result.stdout.strip().split("\n")

        if extensions:
            files = [f for f in files if any(f.endswith(ext) for ext in extensions)]

        return files

    def _get_untracked_files(self) -> list[str]:
        """Получает untracked файлы."""
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )
        return [f for f in result.stdout.strip().split("\n") if f]

    def compute_file_hash(self, file_path: str) -> str:
        """Вычисляет hash содержимого файла."""
        full_path = self.repo_path / file_path
        if not full_path.exists():
            return ""

        content = full_path.read_bytes()
        return hashlib.sha256(content).hexdigest()


class IncrementalIndexer:
    """
    Incremental indexer с git-aware updates.

    Workflow:
    1. Загружаем состояние индекса
    2. Определяем изменения через git
    3. Удаляем чанки для измененных/удаленных файлов
    4. Добавляем чанки для новых/измененных файлов
    5. Сохраняем новое состояние
    """

    STATE_FILE = ".rag_index_state.json"

    # Поддерживаемые языки и расширения
    SUPPORTED_EXTENSIONS = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".rb": "ruby",
        ".php": "php",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".hpp": "cpp",
    }

    def __init__(
        self,
        repo_path: Path,
        qdrant_client: QdrantClient,
        chunker,  # ASTChunker
        embedder,  # Embedding function
    ):
        self.repo_path = repo_path
        self.client = qdrant_client
        self.chunker = chunker
        self.embedder = embedder
        self.git = GitChangeDetector(repo_path)

    async def index(
        self,
        full_reindex: bool = False,
        extensions: list[str] = None,
    ) -> dict:
        """
        Выполняет индексацию.

        Args:
            full_reindex: Полная переиндексация
            extensions: Фильтр по расширениям

        Returns:
            Статистика индексации
        """
        extensions = extensions or list(self.SUPPORTED_EXTENSIONS.keys())

        # 1. Загружаем состояние
        state = self._load_state() if not full_reindex else None

        if state:
            # Incremental update
            return await self._incremental_update(state, extensions)
        else:
            # Full index
            return await self._full_index(extensions)

    async def _full_index(self, extensions: list[str]) -> dict:
        """Полная индексация репозитория."""
        stats = {
            "files_indexed": 0,
            "chunks_created": 0,
            "errors": [],
            "duration_ms": 0,
        }

        start_time = datetime.now()

        # Получаем все файлы
        files = self.git.get_all_tracked_files(extensions)

        # Индексируем файлы
        indexed_files = {}

        for file_path in files:
            try:
                chunks = await self._index_file(file_path)
                file_hash = self.git.compute_file_hash(file_path)
                indexed_files[file_path] = file_hash
                stats["files_indexed"] += 1
                stats["chunks_created"] += len(chunks)
            except Exception as e:
                stats["errors"].append(f"{file_path}: {str(e)}")

        # Сохраняем состояние
        state = IndexState(
            git_commit=self.git.get_current_commit(),
            indexed_files=indexed_files,
            last_updated=datetime.now(),
            total_chunks=stats["chunks_created"],
            total_files=stats["files_indexed"],
        )
        self._save_state(state)

        stats["duration_ms"] = (datetime.now() - start_time).total_seconds() * 1000

        return stats

    async def _incremental_update(
        self,
        state: IndexState,
        extensions: list[str],
    ) -> dict:
        """Incremental update на основе git diff."""
        stats = {
            "files_added": 0,
            "files_modified": 0,
            "files_deleted": 0,
            "chunks_added": 0,
            "chunks_deleted": 0,
            "errors": [],
            "duration_ms": 0,
        }

        start_time = datetime.now()

        # Получаем изменения
        changes = self.git.get_changes_since(state.git_commit)

        # Фильтруем по расширениям
        changes = [c for c in changes if any(c.path.endswith(ext) for ext in extensions)]

        new_indexed_files = dict(state.indexed_files)

        for change in changes:
            try:
                if change.change_type == ChangeType.DELETED:
                    # Удаляем чанки
                    deleted = await self._delete_file_chunks(change.path)
                    stats["files_deleted"] += 1
                    stats["chunks_deleted"] += deleted
                    new_indexed_files.pop(change.path, None)

                elif change.change_type == ChangeType.ADDED:
                    # Добавляем чанки
                    chunks = await self._index_file(change.path)
                    file_hash = self.git.compute_file_hash(change.path)
                    new_indexed_files[change.path] = file_hash
                    stats["files_added"] += 1
                    stats["chunks_added"] += len(chunks)

                elif change.change_type == ChangeType.MODIFIED:
                    # Проверяем, изменился ли content hash
                    new_hash = self.git.compute_file_hash(change.path)
                    old_hash = state.indexed_files.get(change.path)

                    if new_hash != old_hash:
                        # Удаляем старые чанки
                        deleted = await self._delete_file_chunks(change.path)
                        stats["chunks_deleted"] += deleted

                        # Добавляем новые
                        chunks = await self._index_file(change.path)
                        new_indexed_files[change.path] = new_hash
                        stats["files_modified"] += 1
                        stats["chunks_added"] += len(chunks)

                elif change.change_type == ChangeType.RENAMED:
                    # Обновляем путь в индексе
                    await self._rename_file_chunks(change.old_path, change.path)
                    old_hash = new_indexed_files.pop(change.old_path, "")
                    new_indexed_files[change.path] = old_hash
                    stats["files_modified"] += 1

            except Exception as e:
                stats["errors"].append(f"{change.path}: {str(e)}")

        # Сохраняем новое состояние
        new_state = IndexState(
            git_commit=self.git.get_current_commit(),
            indexed_files=new_indexed_files,
            last_updated=datetime.now(),
            total_chunks=state.total_chunks + stats["chunks_added"] - stats["chunks_deleted"],
            total_files=len(new_indexed_files),
        )
        self._save_state(new_state)

        stats["duration_ms"] = (datetime.now() - start_time).total_seconds() * 1000

        return stats

    async def _index_file(self, file_path: str) -> list:
        """Индексирует один файл."""
        full_path = self.repo_path / file_path

        if not full_path.exists():
            return []

        # Определяем язык
        ext = full_path.suffix
        language = self.SUPPORTED_EXTENSIONS.get(ext, "unknown")

        # Чанкаем
        chunks = self.chunker.chunk_file(full_path)

        if not chunks:
            return []

        # Создаем embeddings батчами
        contents = [c.content for c in chunks]
        embeddings = await self._batch_embed(contents)

        # Формируем points для Qdrant
        points = []
        for chunk, embedding in zip(chunks, embeddings):
            point = models.PointStruct(
                id=chunk.id,
                vector={
                    "dense": embedding.tolist(),
                },
                payload={
                    "content": chunk.content,
                    "file_path": file_path,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "chunk_type": chunk.chunk_type.value,
                    "symbol_name": chunk.symbol_name,
                    "parent_symbol": chunk.parent_symbol,
                    "docstring": chunk.docstring,
                    "signature": chunk.signature,
                    "language": language,
                    "tokens": chunk.tokens_estimate,
                    "git_hash": self.git.get_current_commit(),
                },
            )
            points.append(point)

        # Upsert в Qdrant
        self.client.upsert(
            collection_name="code_semantic",
            points=points,
        )

        # Также добавляем symbols
        symbol_points = [p for p, c in zip(points, chunks)
                        if c.chunk_type.value in ("function", "class", "method")]
        if symbol_points:
            self.client.upsert(
                collection_name="code_symbols",
                points=symbol_points,
            )

        return chunks

    async def _delete_file_chunks(self, file_path: str) -> int:
        """Удаляет чанки для файла."""
        # Подсчитываем количество
        count_result = self.client.count(
            collection_name="code_semantic",
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="file_path",
                        match=models.MatchValue(value=file_path),
                    )
                ]
            ),
        )
        deleted_count = count_result.count

        # Удаляем из semantic
        self.client.delete(
            collection_name="code_semantic",
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="file_path",
                            match=models.MatchValue(value=file_path),
                        )
                    ]
                )
            ),
        )

        # Удаляем из symbols
        self.client.delete(
            collection_name="code_symbols",
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="file_path",
                            match=models.MatchValue(value=file_path),
                        )
                    ]
                )
            ),
        )

        return deleted_count

    async def _rename_file_chunks(self, old_path: str, new_path: str):
        """Обновляет path в чанках при переименовании."""
        # Qdrant не поддерживает прямой update payload
        # Получаем все points, обновляем payload, upsert

        # Получаем points
        scroll_result = self.client.scroll(
            collection_name="code_semantic",
            scroll_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="file_path",
                        match=models.MatchValue(value=old_path),
                    )
                ]
            ),
            with_payload=True,
            with_vectors=True,
            limit=1000,
        )

        points = scroll_result[0]

        if not points:
            return

        # Обновляем payload
        updated_points = []
        for point in points:
            point.payload["file_path"] = new_path
            updated_points.append(models.PointStruct(
                id=point.id,
                vector=point.vector,
                payload=point.payload,
            ))

        # Upsert обновленных
        self.client.upsert(
            collection_name="code_semantic",
            points=updated_points,
        )

    async def _batch_embed(self, texts: list[str], batch_size: int = 32):
        """Батчевый embedding."""
        embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            batch_embeddings = await asyncio.gather(
                *[asyncio.to_thread(self.embedder, text) for text in batch]
            )
            embeddings.extend(batch_embeddings)

        return embeddings

    def _load_state(self) -> Optional[IndexState]:
        """Загружает состояние индекса."""
        state_path = self.repo_path / self.STATE_FILE

        if not state_path.exists():
            return None

        try:
            data = json.loads(state_path.read_text())
            return IndexState.from_dict(data)
        except Exception:
            return None

    def _save_state(self, state: IndexState):
        """Сохраняет состояние индекса."""
        state_path = self.repo_path / self.STATE_FILE
        state_path.write_text(json.dumps(state.to_dict(), indent=2))


# === File Watcher для real-time updates ===

class FileWatcher:
    """
    Watches for file changes and triggers re-indexing.

    Использует watchdog для file system events.
    """

    def __init__(
        self,
        indexer: IncrementalIndexer,
        debounce_ms: int = 500,
    ):
        self.indexer = indexer
        self.debounce_ms = debounce_ms
        self._pending_files: set[str] = set()
        self._task: Optional[asyncio.Task] = None

    async def on_file_changed(self, file_path: str):
        """Обрабатывает изменение файла."""
        self._pending_files.add(file_path)

        # Debounce - ждем окончания burst изменений
        if self._task:
            self._task.cancel()

        self._task = asyncio.create_task(self._process_changes())

    async def _process_changes(self):
        """Обрабатывает накопленные изменения."""
        await asyncio.sleep(self.debounce_ms / 1000)

        files = list(self._pending_files)
        self._pending_files.clear()

        for file_path in files:
            # Re-index single file
            await self.indexer._delete_file_chunks(file_path)
            await self.indexer._index_file(file_path)
