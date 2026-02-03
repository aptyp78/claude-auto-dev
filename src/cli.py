#!/usr/bin/env python3
"""
Local Swarm CLI

Единая точка входа для локальной мультиагентной системы разработки.
"""

import asyncio
import argparse
import sys
from pathlib import Path
from typing import Optional
import yaml

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.orchestrator.main_orchestrator import LocalSwarmOrchestrator
from src.quality_gates import (
    QualityGateOrchestrator,
    create_lenient_pipeline,
    create_strict_pipeline,
)
from src.integrations import CodeContextManager, GitIntegration


class LocalSwarmCLI:
    """CLI для Local Swarm"""

    def __init__(self):
        self.parser = self._create_parser()

    def _create_parser(self) -> argparse.ArgumentParser:
        """Создать парсер аргументов"""
        parser = argparse.ArgumentParser(
            prog="local-swarm",
            description="🤖 Local Swarm - Локальная мультиагентная система разработки",
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog="""
Примеры:
  local-swarm run "Добавить авторизацию через JWT"
  local-swarm run --file task.md
  local-swarm check --path ./my-project
  local-swarm status

Режимы:
  run      - Выполнить задачу с полным pipeline
  check    - Только quality gates (без разработки)
  status   - Статус моделей и системы
  config   - Показать текущую конфигурацию
"""
        )

        subparsers = parser.add_subparsers(dest="command", help="Команды")

        # run
        run_parser = subparsers.add_parser("run", help="Выполнить задачу")
        run_parser.add_argument(
            "task",
            nargs="?",
            help="Описание задачи"
        )
        run_parser.add_argument(
            "--file", "-f",
            help="Файл с описанием задачи"
        )
        run_parser.add_argument(
            "--path", "-p",
            default=".",
            help="Путь к проекту (по умолчанию: текущая директория)"
        )
        run_parser.add_argument(
            "--model",
            help="Модель для использования"
        )
        run_parser.add_argument(
            "--no-tests",
            action="store_true",
            help="Пропустить тесты"
        )
        run_parser.add_argument(
            "--no-lint",
            action="store_true",
            help="Пропустить линтер"
        )
        run_parser.add_argument(
            "--auto-commit",
            action="store_true",
            help="Автоматический коммит после успеха"
        )
        run_parser.add_argument(
            "--verbose", "-v",
            action="store_true",
            help="Подробный вывод"
        )

        # check
        check_parser = subparsers.add_parser("check", help="Проверить качество кода")
        check_parser.add_argument(
            "--path", "-p",
            default=".",
            help="Путь к проекту"
        )
        check_parser.add_argument(
            "--fix",
            action="store_true",
            help="Автоматически исправить проблемы"
        )
        check_parser.add_argument(
            "--strict",
            action="store_true",
            help="Строгий режим (все gates blocking)"
        )
        check_parser.add_argument(
            "--quick",
            action="store_true",
            help="Быстрая проверка (только linter и security)"
        )

        # status
        status_parser = subparsers.add_parser("status", help="Статус системы")
        status_parser.add_argument(
            "--models",
            action="store_true",
            help="Показать доступные модели"
        )

        # config
        config_parser = subparsers.add_parser("config", help="Показать конфигурацию")

        return parser

    async def run_task(self, args) -> int:
        """Выполнить задачу"""
        # Получить описание задачи
        task_description = args.task
        if args.file:
            task_file = Path(args.file)
            if task_file.exists():
                task_description = task_file.read_text()
            else:
                print(f"❌ Файл не найден: {args.file}")
                return 1

        if not task_description:
            print("❌ Укажите описание задачи или файл с --file")
            return 1

        project_path = Path(args.path).resolve()
        if not project_path.exists():
            print(f"❌ Путь не существует: {project_path}")
            return 1

        print(f"🚀 Local Swarm запущен")
        print(f"📁 Проект: {project_path}")
        print(f"📝 Задача: {task_description[:100]}...")
        print()

        try:
            # Инициализация оркестратора
            orchestrator = LocalSwarmOrchestrator(
                project_path=str(project_path),
                verbose=args.verbose,
            )

            # Конфигурация
            if args.model:
                orchestrator.default_model = args.model

            # Запуск
            result = await orchestrator.run(task_description)

            # Вывод результата
            print()
            print("=" * 50)
            if result.success:
                print("✅ ЗАДАЧА ВЫПОЛНЕНА")
            else:
                print("❌ ЗАДАЧА НЕ ВЫПОЛНЕНА")
            print("=" * 50)

            if result.summary:
                print(f"\n{result.summary}")

            # Автокоммит
            if args.auto_commit and result.success:
                git = GitIntegration(project_path)
                status = await git.get_status()

                if status.has_changes:
                    commit_msg = f"feat: {task_description[:50]}\n\nGenerated by Local Swarm"
                    commit = await git.auto_commit_if_changed(commit_msg)
                    if commit:
                        print(f"\n📦 Автокоммит: {commit.short_hash} - {commit.message}")

            return 0 if result.success else 1

        except Exception as e:
            print(f"\n❌ Ошибка: {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            return 1

    async def run_check(self, args) -> int:
        """Запустить quality gates"""
        project_path = Path(args.path).resolve()

        print(f"🔍 Проверка качества кода")
        print(f"📁 Проект: {project_path}")
        print()

        # Выбор pipeline
        if args.strict:
            orchestrator = create_strict_pipeline()
            mode = "strict"
        elif args.quick:
            from src.quality_gates import create_quick_pipeline
            orchestrator = create_quick_pipeline()
            mode = "quick"
        else:
            orchestrator = create_lenient_pipeline()
            mode = "standard"

        print(f"⚙️  Режим: {mode}")
        if args.fix:
            print("🔧 Автоисправление включено")
        print()

        # Callbacks для прогресса
        orchestrator.on_gate_start = lambda name: print(f"⏳ {name}...")
        orchestrator.on_gate_complete = lambda r: print(
            f"   {'✅' if r.passed else '❌'} {r.gate_name} ({r.execution_time_seconds:.1f}s)"
        )

        # Запуск
        context = {"project_path": str(project_path)}

        if args.quick:
            result = await orchestrator.run_quick(context)
        else:
            result = await orchestrator.run_full(context)

        # Вывод
        print(result.summary())

        return 0 if result.passed else 1

    async def show_status(self, args) -> int:
        """Показать статус системы"""
        print("🤖 Local Swarm Status")
        print("=" * 40)
        print()

        # Проверка Ollama
        try:
            proc = await asyncio.create_subprocess_exec(
                "ollama", "list",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()

            if proc.returncode == 0:
                print("✅ Ollama: работает")
                if args.models:
                    print("\n📦 Доступные модели:")
                    print(stdout.decode())
            else:
                print("❌ Ollama: не запущен")
                print("   Запустите: ollama serve")
        except FileNotFoundError:
            print("❌ Ollama: не установлен")
            print("   Установите: brew install ollama")

        print()

        # Проверка рекомендуемых моделей
        required_models = ["qwen3-coder:30b", "deepseek-r1:32b", "devstral", "codestral"]
        print("📋 Рекомендуемые модели:")

        for model in required_models:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ollama", "show", model,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate()

                if proc.returncode == 0:
                    print(f"   ✅ {model}")
                else:
                    print(f"   ❌ {model} (не установлена)")
            except:
                print(f"   ❓ {model} (не удалось проверить)")

        return 0

    def show_config(self) -> int:
        """Показать конфигурацию"""
        config_path = Path(__file__).parent.parent / "configs" / "models.yaml"

        if config_path.exists():
            print("📄 Текущая конфигурация:")
            print("=" * 40)
            print(config_path.read_text())
        else:
            print("❌ Конфигурация не найдена")
            print(f"   Ожидается: {config_path}")

        return 0

    async def main(self) -> int:
        """Главная точка входа"""
        args = self.parser.parse_args()

        if not args.command:
            self.parser.print_help()
            return 0

        if args.command == "run":
            return await self.run_task(args)
        elif args.command == "check":
            return await self.run_check(args)
        elif args.command == "status":
            return await self.show_status(args)
        elif args.command == "config":
            return self.show_config()

        return 0


def main():
    """Entry point"""
    cli = LocalSwarmCLI()
    exit_code = asyncio.run(cli.main())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
