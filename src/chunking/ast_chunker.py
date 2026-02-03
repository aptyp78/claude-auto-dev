"""
AST-Based Code Chunker для Code RAG системы.

Понимает структуру кода и создает семантически значимые чанки.
"""

import ast
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional
import tree_sitter_python as tspython
from tree_sitter import Language, Parser


class ChunkType(Enum):
    """Типы чанков для разных уровней индексации."""
    FILE = "file"           # Метаданные файла
    MODULE = "module"       # Import statements, module docstring
    CLASS = "class"         # Класс целиком или его части
    METHOD = "method"       # Метод класса
    FUNCTION = "function"   # Standalone функция
    BLOCK = "block"         # Логический блок кода
    PATTERN = "pattern"     # Паттерн/конвенция


@dataclass
class CodeChunk:
    """Представление чанка кода."""

    # Идентификация
    id: str                          # Уникальный хеш
    file_path: str                   # Путь к файлу
    chunk_type: ChunkType            # Тип чанка

    # Позиция
    start_line: int
    end_line: int
    start_byte: int
    end_byte: int

    # Контент
    content: str                     # Исходный код
    docstring: Optional[str] = None  # Docstring если есть

    # Семантика
    symbol_name: Optional[str] = None    # Имя символа (функция, класс)
    parent_symbol: Optional[str] = None  # Родительский символ
    signature: Optional[str] = None      # Сигнатура функции/метода

    # Связи
    imports: list[str] = field(default_factory=list)      # Импорты
    calls: list[str] = field(default_factory=list)        # Вызываемые функции
    dependencies: list[str] = field(default_factory=list) # Зависимости

    # Метаданные для поиска
    language: str = "python"
    complexity: int = 0              # Cyclomatic complexity
    tokens_estimate: int = 0         # Примерное кол-во токенов

    def compute_id(self) -> str:
        """Вычисляет стабильный ID на основе контента."""
        content_hash = hashlib.sha256(
            f"{self.file_path}:{self.symbol_name}:{self.content}".encode()
        ).hexdigest()[:16]
        return f"{self.chunk_type.value}_{content_hash}"


class ASTChunker:
    """
    Чанкер на основе AST для Python кода.

    Стратегия:
    1. Парсит AST через tree-sitter (быстро и надежно)
    2. Извлекает top-level конструкции (классы, функции)
    3. Разбивает большие конструкции на подчанки
    4. Сохраняет контекст (импорты, docstrings)
    """

    # Лимиты для чанков
    MAX_CHUNK_TOKENS = 512       # Максимум токенов в чанке
    MIN_CHUNK_TOKENS = 50        # Минимум (иначе объединяем)
    OVERLAP_LINES = 3            # Строки перекрытия

    def __init__(self, language: str = "python"):
        self.language = language
        self._init_parser()

    def _init_parser(self):
        """Инициализирует tree-sitter парсер."""
        PY_LANGUAGE = Language(tspython.language())
        self.parser = Parser(PY_LANGUAGE)

    def chunk_file(self, file_path: Path) -> list[CodeChunk]:
        """
        Разбивает файл на семантические чанки.

        Returns:
            Список CodeChunk для индексации
        """
        content = file_path.read_text(encoding='utf-8')
        tree = self.parser.parse(content.encode())

        chunks = []

        # 1. File-level чанк (метаданные)
        file_chunk = self._create_file_chunk(file_path, content, tree)
        chunks.append(file_chunk)

        # 2. Module-level (imports, module docstring)
        module_chunk = self._extract_module_chunk(file_path, content, tree)
        if module_chunk:
            chunks.append(module_chunk)

        # 3. Classes и их методы
        class_chunks = self._extract_classes(file_path, content, tree)
        chunks.extend(class_chunks)

        # 4. Top-level функции
        function_chunks = self._extract_functions(file_path, content, tree)
        chunks.extend(function_chunks)

        # 5. Вычисляем ID для каждого чанка
        for chunk in chunks:
            chunk.id = chunk.compute_id()
            chunk.tokens_estimate = self._estimate_tokens(chunk.content)

        return chunks

    def _create_file_chunk(
        self,
        file_path: Path,
        content: str,
        tree
    ) -> CodeChunk:
        """Создает чанк с метаданными файла."""

        # Собираем информацию о файле
        symbols = self._collect_symbols(tree)
        imports = self._extract_imports(tree, content)

        # Формируем описание файла
        description = self._generate_file_description(
            file_path, symbols, imports
        )

        return CodeChunk(
            id="",  # Вычислится позже
            file_path=str(file_path),
            chunk_type=ChunkType.FILE,
            start_line=0,
            end_line=content.count('\n'),
            start_byte=0,
            end_byte=len(content),
            content=description,
            imports=imports,
            language=self.language
        )

    def _extract_module_chunk(
        self,
        file_path: Path,
        content: str,
        tree
    ) -> Optional[CodeChunk]:
        """Извлекает module-level контент (импорты, docstring)."""

        root = tree.root_node
        module_parts = []
        end_line = 0

        for child in root.children:
            # Module docstring
            if child.type == "expression_statement":
                expr = child.children[0] if child.children else None
                if expr and expr.type == "string":
                    module_parts.append(content[child.start_byte:child.end_byte])
                    end_line = max(end_line, child.end_point[0])

            # Imports
            elif child.type in ("import_statement", "import_from_statement"):
                module_parts.append(content[child.start_byte:child.end_byte])
                end_line = max(end_line, child.end_point[0])

            # Останавливаемся на первом определении
            elif child.type in ("function_definition", "class_definition"):
                break

        if not module_parts:
            return None

        return CodeChunk(
            id="",
            file_path=str(file_path),
            chunk_type=ChunkType.MODULE,
            start_line=0,
            end_line=end_line,
            start_byte=0,
            end_byte=root.children[0].end_byte if root.children else 0,
            content="\n".join(module_parts),
            language=self.language
        )

    def _extract_classes(
        self,
        file_path: Path,
        content: str,
        tree
    ) -> list[CodeChunk]:
        """Извлекает классы и их методы."""

        chunks = []

        for node in self._find_nodes(tree.root_node, "class_definition"):
            class_name = self._get_node_name(node, content)
            class_content = content[node.start_byte:node.end_byte]
            docstring = self._extract_docstring(node, content)

            # Если класс небольшой - один чанк
            if self._estimate_tokens(class_content) <= self.MAX_CHUNK_TOKENS:
                chunks.append(CodeChunk(
                    id="",
                    file_path=str(file_path),
                    chunk_type=ChunkType.CLASS,
                    start_line=node.start_point[0],
                    end_line=node.end_point[0],
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    content=class_content,
                    symbol_name=class_name,
                    docstring=docstring,
                    signature=self._get_class_signature(node, content),
                    language=self.language
                ))
            else:
                # Большой класс - разбиваем на методы
                # Сначала класс без тела (сигнатура + docstring)
                class_header = self._get_class_header(node, content)
                chunks.append(CodeChunk(
                    id="",
                    file_path=str(file_path),
                    chunk_type=ChunkType.CLASS,
                    start_line=node.start_point[0],
                    end_line=node.start_point[0] + class_header.count('\n'),
                    start_byte=node.start_byte,
                    end_byte=node.start_byte + len(class_header),
                    content=class_header,
                    symbol_name=class_name,
                    docstring=docstring,
                    signature=self._get_class_signature(node, content),
                    language=self.language
                ))

                # Затем каждый метод
                for method_node in self._find_nodes(node, "function_definition"):
                    method_name = self._get_node_name(method_node, content)
                    method_content = content[method_node.start_byte:method_node.end_byte]

                    chunks.append(CodeChunk(
                        id="",
                        file_path=str(file_path),
                        chunk_type=ChunkType.METHOD,
                        start_line=method_node.start_point[0],
                        end_line=method_node.end_point[0],
                        start_byte=method_node.start_byte,
                        end_byte=method_node.end_byte,
                        content=method_content,
                        symbol_name=method_name,
                        parent_symbol=class_name,
                        docstring=self._extract_docstring(method_node, content),
                        signature=self._get_function_signature(method_node, content),
                        language=self.language
                    ))

        return chunks

    def _extract_functions(
        self,
        file_path: Path,
        content: str,
        tree
    ) -> list[CodeChunk]:
        """Извлекает top-level функции."""

        chunks = []

        # Ищем только top-level функции (прямые потомки root)
        for node in tree.root_node.children:
            if node.type != "function_definition":
                continue

            func_name = self._get_node_name(node, content)
            func_content = content[node.start_byte:node.end_byte]
            docstring = self._extract_docstring(node, content)

            # Если функция большая - разбиваем по блокам
            if self._estimate_tokens(func_content) > self.MAX_CHUNK_TOKENS:
                sub_chunks = self._split_large_function(
                    file_path, node, content, func_name
                )
                chunks.extend(sub_chunks)
            else:
                chunks.append(CodeChunk(
                    id="",
                    file_path=str(file_path),
                    chunk_type=ChunkType.FUNCTION,
                    start_line=node.start_point[0],
                    end_line=node.end_point[0],
                    start_byte=node.start_byte,
                    end_byte=node.end_byte,
                    content=func_content,
                    symbol_name=func_name,
                    docstring=docstring,
                    signature=self._get_function_signature(node, content),
                    calls=self._extract_calls(node, content),
                    language=self.language
                ))

        return chunks

    def _split_large_function(
        self,
        file_path: Path,
        node,
        content: str,
        func_name: str
    ) -> list[CodeChunk]:
        """Разбивает большую функцию на логические блоки."""

        chunks = []
        func_content = content[node.start_byte:node.end_byte]
        lines = func_content.split('\n')

        # Находим signature + docstring
        header_lines = []
        in_docstring = False
        body_start_idx = 0

        for i, line in enumerate(lines):
            header_lines.append(line)
            if '"""' in line or "'''" in line:
                if in_docstring:
                    body_start_idx = i + 1
                    break
                in_docstring = True
            elif i == 0:  # def line
                continue
            elif not in_docstring and line.strip() and not line.strip().startswith('#'):
                body_start_idx = i
                header_lines.pop()  # Убираем последнюю строку
                break

        # Добавляем header чанк
        header_content = '\n'.join(header_lines)
        chunks.append(CodeChunk(
            id="",
            file_path=str(file_path),
            chunk_type=ChunkType.FUNCTION,
            start_line=node.start_point[0],
            end_line=node.start_point[0] + len(header_lines),
            start_byte=node.start_byte,
            end_byte=node.start_byte + len(header_content),
            content=header_content,
            symbol_name=func_name,
            signature=self._get_function_signature(node, content),
            language=self.language
        ))

        # Разбиваем тело на блоки по ~400 токенов с overlap
        body_lines = lines[body_start_idx:]
        current_block = []
        current_tokens = 0
        block_idx = 0

        for i, line in enumerate(body_lines):
            line_tokens = len(line.split()) + 1  # Грубая оценка

            if current_tokens + line_tokens > 400 and current_block:
                # Сохраняем блок
                block_content = '\n'.join(current_block)
                block_start = node.start_point[0] + body_start_idx + i - len(current_block)

                chunks.append(CodeChunk(
                    id="",
                    file_path=str(file_path),
                    chunk_type=ChunkType.BLOCK,
                    start_line=block_start,
                    end_line=block_start + len(current_block),
                    start_byte=0,  # Приблизительно
                    end_byte=0,
                    content=f"# Part of {func_name}\n{block_content}",
                    symbol_name=f"{func_name}_block_{block_idx}",
                    parent_symbol=func_name,
                    language=self.language
                ))

                # Overlap - оставляем последние 3 строки
                current_block = current_block[-self.OVERLAP_LINES:]
                current_tokens = sum(len(l.split()) + 1 for l in current_block)
                block_idx += 1

            current_block.append(line)
            current_tokens += line_tokens

        # Последний блок
        if current_block:
            block_content = '\n'.join(current_block)
            chunks.append(CodeChunk(
                id="",
                file_path=str(file_path),
                chunk_type=ChunkType.BLOCK,
                start_line=node.end_point[0] - len(current_block),
                end_line=node.end_point[0],
                start_byte=0,
                end_byte=0,
                content=f"# Part of {func_name}\n{block_content}",
                symbol_name=f"{func_name}_block_{block_idx}",
                parent_symbol=func_name,
                language=self.language
            ))

        return chunks

    # === Helper методы ===

    def _find_nodes(self, node, node_type: str):
        """Рекурсивно находит все ноды заданного типа."""
        if node.type == node_type:
            yield node
        for child in node.children:
            yield from self._find_nodes(child, node_type)

    def _get_node_name(self, node, content: str) -> str:
        """Извлекает имя из definition node."""
        for child in node.children:
            if child.type == "identifier":
                return content[child.start_byte:child.end_byte]
        return "unknown"

    def _extract_docstring(self, node, content: str) -> Optional[str]:
        """Извлекает docstring из функции/класса."""
        # Ищем первый expression_statement с string
        body = None
        for child in node.children:
            if child.type == "block":
                body = child
                break

        if not body or not body.children:
            return None

        first_stmt = body.children[0]
        if first_stmt.type == "expression_statement":
            expr = first_stmt.children[0] if first_stmt.children else None
            if expr and expr.type == "string":
                docstring = content[expr.start_byte:expr.end_byte]
                # Убираем кавычки
                return docstring.strip('"""').strip("'''").strip()

        return None

    def _get_function_signature(self, node, content: str) -> str:
        """Извлекает сигнатуру функции."""
        for child in node.children:
            if child.type == "parameters":
                name = self._get_node_name(node, content)
                params = content[child.start_byte:child.end_byte]
                return f"def {name}{params}"
        return ""

    def _get_class_signature(self, node, content: str) -> str:
        """Извлекает сигнатуру класса."""
        name = self._get_node_name(node, content)

        # Ищем argument_list (наследование)
        for child in node.children:
            if child.type == "argument_list":
                args = content[child.start_byte:child.end_byte]
                return f"class {name}{args}"

        return f"class {name}"

    def _get_class_header(self, node, content: str) -> str:
        """Извлекает заголовок класса (до первого метода)."""
        class_start = node.start_byte

        # Находим первый метод
        for child in self._find_nodes(node, "function_definition"):
            method_start = child.start_byte
            return content[class_start:method_start].rstrip()

        # Нет методов - весь класс
        return content[node.start_byte:node.end_byte]

    def _extract_imports(self, tree, content: str) -> list[str]:
        """Извлекает список импортов."""
        imports = []
        for node in tree.root_node.children:
            if node.type == "import_statement":
                # import x, y, z
                for child in node.children:
                    if child.type == "dotted_name":
                        imports.append(content[child.start_byte:child.end_byte])
            elif node.type == "import_from_statement":
                # from x import y
                module = None
                for child in node.children:
                    if child.type == "dotted_name":
                        module = content[child.start_byte:child.end_byte]
                        break
                if module:
                    imports.append(module)
        return imports

    def _extract_calls(self, node, content: str) -> list[str]:
        """Извлекает имена вызываемых функций."""
        calls = []
        for call_node in self._find_nodes(node, "call"):
            # Первый child - function being called
            func = call_node.children[0] if call_node.children else None
            if func:
                if func.type == "identifier":
                    calls.append(content[func.start_byte:func.end_byte])
                elif func.type == "attribute":
                    # obj.method() - берем имя метода
                    for child in func.children:
                        if child.type == "identifier":
                            last_id = content[child.start_byte:child.end_byte]
                    calls.append(last_id)
        return list(set(calls))  # Уникальные

    def _collect_symbols(self, tree) -> dict:
        """Собирает все символы в файле."""
        symbols = {
            "classes": [],
            "functions": [],
            "methods": {}
        }

        for node in tree.root_node.children:
            if node.type == "class_definition":
                # Нужен content для извлечения имени
                # Упрощенно - ищем identifier
                for child in node.children:
                    if child.type == "identifier":
                        class_name = child.text.decode() if hasattr(child, 'text') else "unknown"
                        symbols["classes"].append(class_name)
                        symbols["methods"][class_name] = []

                        # Методы класса
                        for method in self._find_nodes(node, "function_definition"):
                            for mchild in method.children:
                                if mchild.type == "identifier":
                                    method_name = mchild.text.decode() if hasattr(mchild, 'text') else "unknown"
                                    symbols["methods"][class_name].append(method_name)
                                    break
                        break

            elif node.type == "function_definition":
                for child in node.children:
                    if child.type == "identifier":
                        func_name = child.text.decode() if hasattr(child, 'text') else "unknown"
                        symbols["functions"].append(func_name)
                        break

        return symbols

    def _generate_file_description(
        self,
        file_path: Path,
        symbols: dict,
        imports: list[str]
    ) -> str:
        """Генерирует текстовое описание файла для embedding."""

        lines = [
            f"File: {file_path.name}",
            f"Path: {file_path}",
            ""
        ]

        if imports:
            lines.append(f"Imports: {', '.join(imports[:10])}")

        if symbols["classes"]:
            lines.append(f"Classes: {', '.join(symbols['classes'])}")
            for cls, methods in symbols["methods"].items():
                if methods:
                    lines.append(f"  {cls} methods: {', '.join(methods[:10])}")

        if symbols["functions"]:
            lines.append(f"Functions: {', '.join(symbols['functions'])}")

        return '\n'.join(lines)

    def _estimate_tokens(self, text: str) -> int:
        """Грубая оценка количества токенов."""
        # ~4 символа на токен в среднем для кода
        return len(text) // 4


# === Использование ===

if __name__ == "__main__":
    from pathlib import Path

    chunker = ASTChunker()

    # Пример: чанкаем этот файл
    chunks = chunker.chunk_file(Path(__file__))

    for chunk in chunks:
        print(f"\n{'='*60}")
        print(f"Type: {chunk.chunk_type.value}")
        print(f"Symbol: {chunk.symbol_name}")
        print(f"Lines: {chunk.start_line}-{chunk.end_line}")
        print(f"Tokens: ~{chunk.tokens_estimate}")
        print(f"Content preview: {chunk.content[:200]}...")
