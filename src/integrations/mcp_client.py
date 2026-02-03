"""
MCP Client

Клиент для взаимодействия с MCP серверами через stdio.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from pathlib import Path
import subprocess


@dataclass
class MCPToolCall:
    """Вызов MCP инструмента"""
    server: str
    tool: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolResult:
    """Результат вызова MCP инструмента"""
    success: bool
    data: Any = None
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
        }


class MCPClient:
    """
    Клиент для MCP серверов

    Поддерживает вызов инструментов через stdio транспорт.
    В локальном режиме выполняет команды напрямую.
    """

    # Известные MCP серверы и их команды запуска
    MCP_SERVERS = {
        "serena": {
            "command": "npx",
            "args": ["-y", "@anthropic/serena-mcp"],
            "cwd": None,
        },
        "git": {
            "command": "npx",
            "args": ["-y", "@anthropic/git-mcp"],
            "cwd": None,
        },
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@anthropic/filesystem-mcp"],
            "cwd": None,
        },
        "memory": {
            "command": "npx",
            "args": ["-y", "@anthropic/memory-mcp"],
            "cwd": None,
        },
    }

    def __init__(self, working_dir: Optional[Path] = None):
        """
        Args:
            working_dir: Рабочая директория для команд
        """
        self.working_dir = working_dir or Path.cwd()
        self._processes: Dict[str, asyncio.subprocess.Process] = {}
        self._request_id = 0

    async def _get_process(self, server: str) -> asyncio.subprocess.Process:
        """Получить или создать процесс для сервера"""
        if server in self._processes:
            proc = self._processes[server]
            if proc.returncode is None:  # Ещё работает
                return proc

        # Запустить новый процесс
        if server not in self.MCP_SERVERS:
            raise ValueError(f"Unknown MCP server: {server}")

        config = self.MCP_SERVERS[server]
        cmd = [config["command"]] + config["args"]
        cwd = config.get("cwd") or str(self.working_dir)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._processes[server] = proc
        return proc

    def _next_request_id(self) -> int:
        """Следующий ID запроса"""
        self._request_id += 1
        return self._request_id

    async def call_tool(self, call: MCPToolCall, timeout: int = 30) -> MCPToolResult:
        """
        Вызвать инструмент MCP сервера

        Args:
            call: MCPToolCall с сервером, инструментом и параметрами
            timeout: Таймаут в секундах

        Returns:
            MCPToolResult
        """
        try:
            # Формируем JSON-RPC запрос
            request = {
                "jsonrpc": "2.0",
                "id": self._next_request_id(),
                "method": "tools/call",
                "params": {
                    "name": call.tool,
                    "arguments": call.params,
                }
            }

            proc = await self._get_process(call.server)

            # Отправляем запрос
            request_bytes = (json.dumps(request) + "\n").encode()
            proc.stdin.write(request_bytes)
            await proc.stdin.drain()

            # Читаем ответ с таймаутом
            try:
                response_line = await asyncio.wait_for(
                    proc.stdout.readline(),
                    timeout=timeout
                )

                if not response_line:
                    return MCPToolResult(
                        success=False,
                        error="Empty response from server"
                    )

                response = json.loads(response_line.decode())

                if "error" in response:
                    return MCPToolResult(
                        success=False,
                        error=response["error"].get("message", str(response["error"]))
                    )

                return MCPToolResult(
                    success=True,
                    data=response.get("result")
                )

            except asyncio.TimeoutError:
                return MCPToolResult(
                    success=False,
                    error=f"Timeout after {timeout}s"
                )

        except Exception as e:
            return MCPToolResult(
                success=False,
                error=str(e)
            )

    async def close(self):
        """Закрыть все процессы"""
        for proc in self._processes.values():
            if proc.returncode is None:
                proc.terminate()
                await proc.wait()
        self._processes.clear()

    # Convenience методы для частых операций

    async def git_status(self) -> MCPToolResult:
        """Получить git status"""
        return await self.call_tool(MCPToolCall(
            server="git",
            tool="git_status",
            params={"repo_path": str(self.working_dir)}
        ))

    async def git_diff(self, staged: bool = False) -> MCPToolResult:
        """Получить git diff"""
        tool = "git_diff_staged" if staged else "git_diff_unstaged"
        return await self.call_tool(MCPToolCall(
            server="git",
            tool=tool,
            params={"repo_path": str(self.working_dir)}
        ))

    async def git_commit(self, message: str) -> MCPToolResult:
        """Создать коммит"""
        return await self.call_tool(MCPToolCall(
            server="git",
            tool="git_commit",
            params={
                "repo_path": str(self.working_dir),
                "message": message,
            }
        ))

    async def read_file(self, file_path: str) -> MCPToolResult:
        """Прочитать файл"""
        return await self.call_tool(MCPToolCall(
            server="filesystem",
            tool="read_file",
            params={"path": file_path}
        ))

    async def write_file(self, file_path: str, content: str) -> MCPToolResult:
        """Записать файл"""
        return await self.call_tool(MCPToolCall(
            server="filesystem",
            tool="write_file",
            params={
                "path": file_path,
                "content": content,
            }
        ))

    async def list_directory(self, path: str = ".") -> MCPToolResult:
        """Список файлов в директории"""
        return await self.call_tool(MCPToolCall(
            server="filesystem",
            tool="list_directory",
            params={"path": path}
        ))


class LocalMCPClient(MCPClient):
    """
    Локальная реализация MCP клиента

    Выполняет операции напрямую без запуска MCP серверов.
    Оптимизировано для полностью локальной работы.
    """

    def __init__(self, working_dir: Optional[Path] = None):
        super().__init__(working_dir)

    async def call_tool(self, call: MCPToolCall, timeout: int = 30) -> MCPToolResult:
        """Выполнить инструмент локально"""
        try:
            if call.server == "git":
                return await self._git_tool(call.tool, call.params)
            elif call.server == "filesystem":
                return await self._filesystem_tool(call.tool, call.params)
            else:
                # Fallback к MCP серверу
                return await super().call_tool(call, timeout)

        except Exception as e:
            return MCPToolResult(success=False, error=str(e))

    async def _git_tool(self, tool: str, params: dict) -> MCPToolResult:
        """Выполнить git команду локально"""
        repo_path = params.get("repo_path", str(self.working_dir))

        git_commands = {
            "git_status": ["git", "status", "--porcelain"],
            "git_diff_unstaged": ["git", "diff"],
            "git_diff_staged": ["git", "diff", "--staged"],
            "git_log": ["git", "log", "--oneline", "-10"],
            "git_branch": ["git", "branch", "-a"],
        }

        if tool in git_commands:
            result = await asyncio.create_subprocess_exec(
                *git_commands[tool],
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode == 0:
                return MCPToolResult(success=True, data=stdout.decode())
            else:
                return MCPToolResult(success=False, error=stderr.decode())

        elif tool == "git_commit":
            message = params.get("message", "")
            result = await asyncio.create_subprocess_exec(
                "git", "commit", "-m", message,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode == 0:
                return MCPToolResult(success=True, data=stdout.decode())
            else:
                return MCPToolResult(success=False, error=stderr.decode())

        elif tool == "git_add":
            files = params.get("files", ["."])
            if isinstance(files, str):
                files = [files]

            result = await asyncio.create_subprocess_exec(
                "git", "add", *files,
                cwd=repo_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await result.communicate()

            if result.returncode == 0:
                return MCPToolResult(success=True, data="Files added")
            else:
                return MCPToolResult(success=False, error=stderr.decode())

        return MCPToolResult(success=False, error=f"Unknown git tool: {tool}")

    async def _filesystem_tool(self, tool: str, params: dict) -> MCPToolResult:
        """Выполнить filesystem команду локально"""
        if tool == "read_file":
            path = Path(params.get("path", ""))
            if not path.is_absolute():
                path = self.working_dir / path

            if not path.exists():
                return MCPToolResult(success=False, error=f"File not found: {path}")

            content = path.read_text(encoding="utf-8", errors="replace")
            return MCPToolResult(success=True, data=content)

        elif tool == "write_file":
            path = Path(params.get("path", ""))
            content = params.get("content", "")

            if not path.is_absolute():
                path = self.working_dir / path

            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            return MCPToolResult(success=True, data=f"Written: {path}")

        elif tool == "list_directory":
            path = Path(params.get("path", "."))
            if not path.is_absolute():
                path = self.working_dir / path

            if not path.exists():
                return MCPToolResult(success=False, error=f"Directory not found: {path}")

            files = sorted([f.name for f in path.iterdir()])
            return MCPToolResult(success=True, data=files)

        elif tool == "create_directory":
            path = Path(params.get("path", ""))
            if not path.is_absolute():
                path = self.working_dir / path

            path.mkdir(parents=True, exist_ok=True)
            return MCPToolResult(success=True, data=f"Created: {path}")

        return MCPToolResult(success=False, error=f"Unknown filesystem tool: {tool}")
