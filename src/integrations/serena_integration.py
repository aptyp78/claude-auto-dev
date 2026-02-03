"""
Serena Integration

Интеграция с Serena MCP для семантического анализа кода.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path

from .mcp_client import MCPClient, MCPToolCall, MCPToolResult, LocalMCPClient


@dataclass
class Symbol:
    """Символ в коде (класс, функция, метод)"""
    name: str
    kind: str  # class, function, method, variable
    path: str  # name_path: Module/Class/method
    file: str
    line: int
    signature: Optional[str] = None
    docstring: Optional[str] = None
    body: Optional[str] = None


@dataclass
class CodeOverview:
    """Обзор кода в файле или директории"""
    files: int = 0
    classes: int = 0
    functions: int = 0
    lines: int = 0
    symbols: List[Symbol] = field(default_factory=list)


class SerenaIntegration:
    """
    Интеграция с Serena для семантического анализа кода

    Serena предоставляет:
    - Символический анализ (классы, функции, методы)
    - Поиск референсов
    - Навигацию по коду
    - Память проекта (memories)
    """

    def __init__(
        self,
        project_path: Path,
        use_local: bool = True
    ):
        """
        Args:
            project_path: Путь к проекту
            use_local: Использовать локальную реализацию вместо MCP
        """
        self.project_path = Path(project_path)
        self.use_local = use_local

        if use_local:
            self.client = LocalMCPClient(self.project_path)
        else:
            self.client = MCPClient(self.project_path)

        # Кэш символов
        self._symbol_cache: Dict[str, List[Symbol]] = {}

    async def get_symbols_overview(
        self,
        relative_path: Optional[str] = None,
        depth: int = 2
    ) -> CodeOverview:
        """
        Получить обзор символов в файле или директории

        Args:
            relative_path: Относительный путь (None = весь проект)
            depth: Глубина анализа символов

        Returns:
            CodeOverview со списком символов
        """
        if self.use_local:
            return await self._local_symbols_overview(relative_path, depth)

        result = await self.client.call_tool(MCPToolCall(
            server="serena",
            tool="jet_brains_get_symbols_overview",
            params={
                "relative_path": relative_path,
                "depth": depth,
            }
        ))

        if result.success and result.data:
            return self._parse_overview(result.data)

        return CodeOverview()

    async def find_symbol(
        self,
        name_path: str,
        include_body: bool = False,
        depth: int = 0
    ) -> Optional[Symbol]:
        """
        Найти символ по пути

        Args:
            name_path: Путь к символу (например, "MyClass/my_method")
            include_body: Включить тело символа
            depth: Глубина дочерних символов

        Returns:
            Symbol или None
        """
        if self.use_local:
            return await self._local_find_symbol(name_path, include_body)

        result = await self.client.call_tool(MCPToolCall(
            server="serena",
            tool="jet_brains_find_symbol",
            params={
                "name_path_pattern": name_path,
                "include_body": include_body,
                "depth": depth,
            }
        ))

        if result.success and result.data:
            return self._parse_symbol(result.data)

        return None

    async def find_references(
        self,
        symbol_path: str,
        relative_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Найти все использования символа

        Args:
            symbol_path: Путь к символу
            relative_path: Ограничить поиск файлом/директорией

        Returns:
            Список референсов
        """
        if self.use_local:
            return await self._local_find_references(symbol_path, relative_path)

        result = await self.client.call_tool(MCPToolCall(
            server="serena",
            tool="jet_brains_find_referencing_symbols",
            params={
                "symbol_name_path": symbol_path,
                "relative_path": relative_path,
            }
        ))

        if result.success and result.data:
            return result.data

        return []

    async def get_type_hierarchy(
        self,
        symbol_path: str
    ) -> Dict[str, Any]:
        """
        Получить иерархию типов для символа

        Args:
            symbol_path: Путь к символу

        Returns:
            Иерархия типов
        """
        result = await self.client.call_tool(MCPToolCall(
            server="serena",
            tool="jet_brains_type_hierarchy",
            params={"symbol_name_path": symbol_path}
        ))

        if result.success and result.data:
            return result.data

        return {}

    # Память проекта

    async def write_memory(self, name: str, content: str) -> bool:
        """Записать в память проекта"""
        result = await self.client.call_tool(MCPToolCall(
            server="serena",
            tool="write_memory",
            params={"name": name, "content": content}
        ))
        return result.success

    async def read_memory(self, name: str) -> Optional[str]:
        """Прочитать из памяти проекта"""
        result = await self.client.call_tool(MCPToolCall(
            server="serena",
            tool="read_memory",
            params={"name": name}
        ))
        if result.success:
            return result.data
        return None

    async def list_memories(self) -> List[str]:
        """Список всех записей в памяти"""
        result = await self.client.call_tool(MCPToolCall(
            server="serena",
            tool="list_memories",
            params={}
        ))
        if result.success and result.data:
            return result.data
        return []

    # Локальная реализация (без MCP сервера)

    async def _local_symbols_overview(
        self,
        relative_path: Optional[str],
        depth: int
    ) -> CodeOverview:
        """Локальный анализ символов через AST"""
        import ast

        target_path = self.project_path
        if relative_path:
            target_path = self.project_path / relative_path

        symbols = []
        files = 0
        lines = 0

        # Определяем файлы для анализа
        if target_path.is_file():
            py_files = [target_path] if target_path.suffix == ".py" else []
        else:
            py_files = list(target_path.rglob("*.py"))

        for py_file in py_files:
            # Пропускаем виртуальные окружения и кэши
            path_str = str(py_file)
            if any(skip in path_str for skip in [
                "/.venv/", "/venv/", "/__pycache__/",
                "/node_modules/", "/.git/"
            ]):
                continue

            files += 1

            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                lines += len(content.split("\n"))

                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef):
                        symbols.append(Symbol(
                            name=node.name,
                            kind="class",
                            path=node.name,
                            file=str(py_file.relative_to(self.project_path)),
                            line=node.lineno,
                            docstring=ast.get_docstring(node),
                        ))

                        # Методы класса
                        if depth >= 1:
                            for item in node.body:
                                if isinstance(item, ast.FunctionDef):
                                    symbols.append(Symbol(
                                        name=item.name,
                                        kind="method",
                                        path=f"{node.name}/{item.name}",
                                        file=str(py_file.relative_to(self.project_path)),
                                        line=item.lineno,
                                        docstring=ast.get_docstring(item),
                                    ))

                    elif isinstance(node, ast.FunctionDef):
                        # Только функции верхнего уровня
                        if not any(isinstance(p, ast.ClassDef) for p in ast.walk(tree)):
                            symbols.append(Symbol(
                                name=node.name,
                                kind="function",
                                path=node.name,
                                file=str(py_file.relative_to(self.project_path)),
                                line=node.lineno,
                                docstring=ast.get_docstring(node),
                            ))

            except SyntaxError:
                continue

        return CodeOverview(
            files=files,
            classes=len([s for s in symbols if s.kind == "class"]),
            functions=len([s for s in symbols if s.kind in ["function", "method"]]),
            lines=lines,
            symbols=symbols,
        )

    async def _local_find_symbol(
        self,
        name_path: str,
        include_body: bool
    ) -> Optional[Symbol]:
        """Локальный поиск символа"""
        import ast

        parts = name_path.split("/")
        target_name = parts[-1]
        parent_name = parts[0] if len(parts) > 1 else None

        for py_file in self.project_path.rglob("*.py"):
            path_str = str(py_file)
            if any(skip in path_str for skip in [
                "/.venv/", "/venv/", "/__pycache__/"
            ]):
                continue

            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content)
                lines = content.split("\n")

                for node in ast.walk(tree):
                    if isinstance(node, ast.ClassDef) and node.name == target_name:
                        if parent_name is None:
                            body = None
                            if include_body:
                                body = "\n".join(lines[node.lineno - 1:node.end_lineno])

                            return Symbol(
                                name=node.name,
                                kind="class",
                                path=node.name,
                                file=str(py_file.relative_to(self.project_path)),
                                line=node.lineno,
                                docstring=ast.get_docstring(node),
                                body=body,
                            )

                    elif isinstance(node, ast.ClassDef) and node.name == parent_name:
                        for item in node.body:
                            if isinstance(item, ast.FunctionDef) and item.name == target_name:
                                body = None
                                if include_body:
                                    body = "\n".join(lines[item.lineno - 1:item.end_lineno])

                                return Symbol(
                                    name=item.name,
                                    kind="method",
                                    path=f"{node.name}/{item.name}",
                                    file=str(py_file.relative_to(self.project_path)),
                                    line=item.lineno,
                                    docstring=ast.get_docstring(item),
                                    body=body,
                                )

                    elif isinstance(node, ast.FunctionDef) and node.name == target_name:
                        if parent_name is None:
                            body = None
                            if include_body:
                                body = "\n".join(lines[node.lineno - 1:node.end_lineno])

                            return Symbol(
                                name=node.name,
                                kind="function",
                                path=node.name,
                                file=str(py_file.relative_to(self.project_path)),
                                line=node.lineno,
                                docstring=ast.get_docstring(node),
                                body=body,
                            )

            except SyntaxError:
                continue

        return None

    async def _local_find_references(
        self,
        symbol_path: str,
        relative_path: Optional[str]
    ) -> List[Dict[str, Any]]:
        """Локальный поиск референсов через grep"""
        import re

        symbol_name = symbol_path.split("/")[-1]
        references = []

        target_path = self.project_path
        if relative_path:
            target_path = self.project_path / relative_path

        # Простой поиск по имени
        pattern = re.compile(rf'\b{re.escape(symbol_name)}\b')

        py_files = target_path.rglob("*.py") if target_path.is_dir() else [target_path]

        for py_file in py_files:
            path_str = str(py_file)
            if any(skip in path_str for skip in ["/.venv/", "/venv/", "/__pycache__/"]):
                continue

            try:
                content = py_file.read_text(encoding="utf-8", errors="replace")

                for i, line in enumerate(content.split("\n"), 1):
                    if pattern.search(line):
                        references.append({
                            "file": str(py_file.relative_to(self.project_path)),
                            "line": i,
                            "text": line.strip(),
                        })

            except Exception:
                continue

        return references

    def _parse_overview(self, data: Any) -> CodeOverview:
        """Парсинг ответа Serena"""
        if isinstance(data, dict):
            symbols = []
            for sym_data in data.get("symbols", []):
                symbols.append(self._parse_symbol(sym_data))

            return CodeOverview(
                files=data.get("files", 0),
                classes=data.get("classes", 0),
                functions=data.get("functions", 0),
                lines=data.get("lines", 0),
                symbols=symbols,
            )
        return CodeOverview()

    def _parse_symbol(self, data: Any) -> Optional[Symbol]:
        """Парсинг символа из ответа Serena"""
        if isinstance(data, dict):
            return Symbol(
                name=data.get("name", ""),
                kind=data.get("kind", "unknown"),
                path=data.get("path", ""),
                file=data.get("file", ""),
                line=data.get("line", 0),
                signature=data.get("signature"),
                docstring=data.get("docstring"),
                body=data.get("body"),
            )
        return None

    async def close(self):
        """Закрыть клиент"""
        await self.client.close()
