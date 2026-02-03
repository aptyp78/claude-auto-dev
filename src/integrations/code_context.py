"""
Code Context Manager

Умное управление контекстом кода для агентов.
Комбинирует AST анализ, git историю и семантический поиск.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set
from pathlib import Path

from .serena_integration import SerenaIntegration, Symbol, CodeOverview
from .git_integration import GitIntegration, GitStatus


@dataclass
class CodeContext:
    """Контекст кода для агента"""
    # Проект
    project_path: str = ""
    language: str = "python"

    # Git состояние
    branch: str = "main"
    changed_files: List[str] = field(default_factory=list)
    git_status: Optional[GitStatus] = None

    # Код
    relevant_symbols: List[Symbol] = field(default_factory=list)
    relevant_files: List[str] = field(default_factory=list)
    code_snippets: Dict[str, str] = field(default_factory=dict)

    # Статистика
    total_files: int = 0
    total_lines: int = 0

    # Ограничения
    max_context_tokens: int = 16000  # Примерный лимит

    def to_prompt_context(self) -> str:
        """Преобразовать в текст для промпта"""
        parts = []

        # Заголовок
        parts.append(f"## Project: {Path(self.project_path).name}")
        parts.append(f"Language: {self.language}")
        parts.append(f"Branch: {self.branch}")
        parts.append("")

        # Изменённые файлы
        if self.changed_files:
            parts.append("### Changed Files:")
            for f in self.changed_files[:10]:
                parts.append(f"- {f}")
            if len(self.changed_files) > 10:
                parts.append(f"... and {len(self.changed_files) - 10} more")
            parts.append("")

        # Релевантные символы
        if self.relevant_symbols:
            parts.append("### Relevant Symbols:")
            for sym in self.relevant_symbols[:20]:
                doc = f" - {sym.docstring[:50]}..." if sym.docstring else ""
                parts.append(f"- {sym.kind}: {sym.path} ({sym.file}:{sym.line}){doc}")
            parts.append("")

        # Код
        if self.code_snippets:
            parts.append("### Code Context:")
            for file_path, code in list(self.code_snippets.items())[:5]:
                parts.append(f"\n```{self.language}")
                parts.append(f"# {file_path}")
                # Ограничиваем размер кода
                lines = code.split("\n")
                if len(lines) > 50:
                    parts.append("\n".join(lines[:25]))
                    parts.append("# ... (truncated)")
                    parts.append("\n".join(lines[-25:]))
                else:
                    parts.append(code)
                parts.append("```")
            parts.append("")

        return "\n".join(parts)

    def estimate_tokens(self) -> int:
        """Оценить количество токенов"""
        text = self.to_prompt_context()
        # Примерно 4 символа на токен
        return len(text) // 4


class CodeContextManager:
    """
    Менеджер контекста кода

    Собирает релевантный контекст для задачи:
    - Анализирует изменённые файлы
    - Находит связанные символы
    - Строит граф зависимостей
    - Оптимизирует размер контекста
    """

    def __init__(
        self,
        project_path: Path,
        max_context_tokens: int = 16000
    ):
        """
        Args:
            project_path: Путь к проекту
            max_context_tokens: Максимальный размер контекста в токенах
        """
        self.project_path = Path(project_path)
        self.max_context_tokens = max_context_tokens

        # Интеграции
        self.serena = SerenaIntegration(project_path, use_local=True)
        self.git = GitIntegration(project_path)

        # Кэш
        self._overview_cache: Optional[CodeOverview] = None
        self._file_cache: Dict[str, str] = {}

    async def build_context(
        self,
        task_description: str,
        files: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
        include_git_changes: bool = True
    ) -> CodeContext:
        """
        Построить контекст для задачи

        Args:
            task_description: Описание задачи
            files: Конкретные файлы
            symbols: Конкретные символы
            include_git_changes: Включить изменённые файлы

        Returns:
            CodeContext
        """
        context = CodeContext(
            project_path=str(self.project_path),
            language=self._detect_language(),
            max_context_tokens=self.max_context_tokens,
        )

        # Git статус
        if include_git_changes:
            context.git_status = await self.git.get_status()
            context.branch = context.git_status.branch
            context.changed_files = (
                context.git_status.staged +
                context.git_status.modified +
                context.git_status.untracked
            )

        # Получить обзор проекта
        if not self._overview_cache:
            self._overview_cache = await self.serena.get_symbols_overview()

        context.total_files = self._overview_cache.files
        context.total_lines = self._overview_cache.lines

        # Найти релевантные символы
        relevant_symbols = await self._find_relevant_symbols(
            task_description,
            files,
            symbols
        )
        context.relevant_symbols = relevant_symbols[:30]  # Ограничиваем

        # Найти релевантные файлы
        relevant_files = await self._find_relevant_files(
            task_description,
            files,
            context.changed_files
        )
        context.relevant_files = relevant_files

        # Загрузить код
        context.code_snippets = await self._load_code_snippets(
            relevant_files[:5],  # Топ 5 файлов
            relevant_symbols[:10]  # Топ 10 символов
        )

        # Оптимизировать размер
        context = self._optimize_context_size(context)

        return context

    async def build_context_for_files(
        self,
        files: List[str]
    ) -> CodeContext:
        """Построить контекст для конкретных файлов"""
        context = CodeContext(
            project_path=str(self.project_path),
            language=self._detect_language(),
            max_context_tokens=self.max_context_tokens,
        )

        context.relevant_files = files

        # Символы из файлов
        for file_path in files:
            overview = await self.serena.get_symbols_overview(file_path, depth=1)
            context.relevant_symbols.extend(overview.symbols)

        # Код
        context.code_snippets = await self._load_code_snippets(files, [])

        return context

    async def build_context_for_symbol(
        self,
        symbol_path: str,
        include_references: bool = True
    ) -> CodeContext:
        """Построить контекст для символа"""
        context = CodeContext(
            project_path=str(self.project_path),
            language=self._detect_language(),
            max_context_tokens=self.max_context_tokens,
        )

        # Найти символ
        symbol = await self.serena.find_symbol(symbol_path, include_body=True)
        if symbol:
            context.relevant_symbols.append(symbol)
            context.relevant_files.append(symbol.file)

            if symbol.body:
                context.code_snippets[f"{symbol.file}:{symbol.path}"] = symbol.body

        # Референсы
        if include_references:
            refs = await self.serena.find_references(symbol_path)
            for ref in refs[:20]:
                context.relevant_files.append(ref["file"])

        # Уникальные файлы
        context.relevant_files = list(set(context.relevant_files))

        return context

    async def get_changed_context(self) -> CodeContext:
        """Контекст для изменённых файлов"""
        status = await self.git.get_status()

        changed = status.staged + status.modified

        if not changed:
            return CodeContext(
                project_path=str(self.project_path),
                language=self._detect_language(),
            )

        return await self.build_context_for_files(changed)

    def _detect_language(self) -> str:
        """Определить язык проекта"""
        if (self.project_path / "pyproject.toml").exists():
            return "python"
        if (self.project_path / "requirements.txt").exists():
            return "python"
        if (self.project_path / "tsconfig.json").exists():
            return "typescript"
        if (self.project_path / "package.json").exists():
            return "javascript"
        if (self.project_path / "go.mod").exists():
            return "go"
        if (self.project_path / "Cargo.toml").exists():
            return "rust"
        return "python"  # Default

    async def _find_relevant_symbols(
        self,
        task_description: str,
        files: Optional[List[str]],
        symbols: Optional[List[str]]
    ) -> List[Symbol]:
        """Найти релевантные символы"""
        result_symbols = []

        # Если указаны конкретные символы
        if symbols:
            for sym_path in symbols:
                sym = await self.serena.find_symbol(sym_path, include_body=True)
                if sym:
                    result_symbols.append(sym)

        # Символы из указанных файлов
        if files:
            for file_path in files:
                overview = await self.serena.get_symbols_overview(file_path, depth=1)
                result_symbols.extend(overview.symbols)

        # Поиск по ключевым словам из описания задачи
        if not result_symbols and self._overview_cache:
            keywords = self._extract_keywords(task_description)

            for symbol in self._overview_cache.symbols:
                name_lower = symbol.name.lower()
                if any(kw in name_lower for kw in keywords):
                    result_symbols.append(symbol)

        return result_symbols

    async def _find_relevant_files(
        self,
        task_description: str,
        explicit_files: Optional[List[str]],
        changed_files: List[str]
    ) -> List[str]:
        """Найти релевантные файлы"""
        files: Set[str] = set()

        # Явно указанные файлы
        if explicit_files:
            files.update(explicit_files)

        # Изменённые файлы
        files.update(changed_files)

        # Файлы из символов
        if self._overview_cache:
            keywords = self._extract_keywords(task_description)

            for symbol in self._overview_cache.symbols:
                if any(kw in symbol.name.lower() for kw in keywords):
                    files.add(symbol.file)

        return list(files)

    async def _load_code_snippets(
        self,
        files: List[str],
        symbols: List[Symbol]
    ) -> Dict[str, str]:
        """Загрузить фрагменты кода"""
        snippets = {}

        # Код символов
        for symbol in symbols:
            if symbol.body:
                key = f"{symbol.file}:{symbol.path}"
                snippets[key] = symbol.body

        # Файлы целиком (если небольшие)
        for file_path in files:
            if file_path in self._file_cache:
                content = self._file_cache[file_path]
            else:
                full_path = self.project_path / file_path
                if full_path.exists():
                    try:
                        content = full_path.read_text(encoding="utf-8", errors="replace")
                        self._file_cache[file_path] = content
                    except Exception:
                        continue
                else:
                    continue

            # Ограничиваем размер файла
            if len(content) < 10000:  # ~2500 токенов
                snippets[file_path] = content

        return snippets

    def _extract_keywords(self, text: str) -> List[str]:
        """Извлечь ключевые слова из текста"""
        # Простой извлечение слов > 3 символов
        words = text.lower().split()
        keywords = []

        # Убираем стоп-слова
        stop_words = {
            "the", "and", "for", "with", "this", "that", "from",
            "have", "has", "had", "will", "would", "could", "should",
            "create", "add", "update", "fix", "implement", "make",
            "need", "want", "please", "code", "file", "function",
        }

        for word in words:
            # Очищаем от пунктуации
            clean = "".join(c for c in word if c.isalnum())
            if len(clean) > 3 and clean not in stop_words:
                keywords.append(clean)

        return list(set(keywords))[:10]  # Топ 10 уникальных

    def _optimize_context_size(self, context: CodeContext) -> CodeContext:
        """Оптимизировать размер контекста"""
        # Оцениваем текущий размер
        current_tokens = context.estimate_tokens()

        if current_tokens <= self.max_context_tokens:
            return context

        # Уменьшаем контекст
        ratio = self.max_context_tokens / current_tokens

        # Уменьшаем количество символов
        new_symbol_count = max(5, int(len(context.relevant_symbols) * ratio))
        context.relevant_symbols = context.relevant_symbols[:new_symbol_count]

        # Уменьшаем количество сниппетов
        new_snippet_count = max(2, int(len(context.code_snippets) * ratio))
        context.code_snippets = dict(
            list(context.code_snippets.items())[:new_snippet_count]
        )

        return context

    async def close(self):
        """Закрыть ресурсы"""
        await self.serena.close()
