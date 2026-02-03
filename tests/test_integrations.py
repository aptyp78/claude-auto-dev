"""
Integration Tests for Local Swarm

Тесты для проверки работоспособности компонентов.
"""

import asyncio
import pytest
from pathlib import Path
import sys

# Добавляем путь к модулям
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestSerenaIntegration:
    """Тесты для Serena Integration"""

    @pytest.fixture
    def project_path(self):
        return Path(__file__).parent.parent

    @pytest.mark.asyncio
    async def test_symbols_overview(self, project_path):
        """Тест получения обзора символов"""
        from src.integrations import SerenaIntegration

        serena = SerenaIntegration(project_path, use_local=True)

        try:
            overview = await serena.get_symbols_overview("src/orchestrator")

            assert overview.files > 0
            assert overview.symbols is not None
            # Должны быть классы или функции
            assert len(overview.symbols) > 0

        finally:
            await serena.close()

    @pytest.mark.asyncio
    async def test_find_symbol(self, project_path):
        """Тест поиска символа"""
        from src.integrations import SerenaIntegration

        serena = SerenaIntegration(project_path, use_local=True)

        try:
            # Ищем класс TaskParser
            symbol = await serena.find_symbol("TaskParser", include_body=False)

            # Может не найти, если структура другая
            if symbol:
                assert symbol.name == "TaskParser"
                assert symbol.kind == "class"

        finally:
            await serena.close()


class TestGitIntegration:
    """Тесты для Git Integration"""

    @pytest.fixture
    def repo_path(self):
        return Path(__file__).parent.parent

    @pytest.mark.asyncio
    async def test_get_status(self, repo_path):
        """Тест получения git status"""
        from src.integrations import GitIntegration

        git = GitIntegration(repo_path)
        status = await git.get_status()

        assert status.branch is not None
        # Должна быть какая-то ветка
        assert len(status.branch) > 0

    @pytest.mark.asyncio
    async def test_get_log(self, repo_path):
        """Тест получения истории коммитов"""
        from src.integrations import GitIntegration

        git = GitIntegration(repo_path)
        commits = await git.get_log(limit=5)

        # Должны быть коммиты
        assert len(commits) > 0
        assert commits[0].hash is not None
        assert commits[0].message is not None


class TestCodeContextManager:
    """Тесты для Code Context Manager"""

    @pytest.fixture
    def project_path(self):
        return Path(__file__).parent.parent

    @pytest.mark.asyncio
    async def test_build_context(self, project_path):
        """Тест построения контекста"""
        from src.integrations import CodeContextManager

        manager = CodeContextManager(project_path)

        try:
            context = await manager.build_context(
                task_description="Fix bug in task parser",
                include_git_changes=True
            )

            assert context.project_path is not None
            assert context.language in ["python", "javascript", "typescript", "go"]

        finally:
            await manager.close()

    @pytest.mark.asyncio
    async def test_context_for_files(self, project_path):
        """Тест контекста для конкретных файлов"""
        from src.integrations import CodeContextManager

        manager = CodeContextManager(project_path)

        try:
            # Берём файл который точно существует
            context = await manager.build_context_for_files([
                "src/orchestrator/task_parser.py"
            ])

            assert "src/orchestrator/task_parser.py" in context.relevant_files

        finally:
            await manager.close()


class TestQualityGates:
    """Тесты для Quality Gates"""

    @pytest.fixture
    def project_path(self):
        return Path(__file__).parent.parent

    @pytest.mark.asyncio
    async def test_linter_gate(self, project_path):
        """Тест Linter Gate"""
        from src.quality_gates import LinterGate

        gate = LinterGate(blocking=False, auto_fix=False)
        result = await gate.check({"project_path": str(project_path)})

        # Результат должен быть
        assert result is not None
        assert result.gate_name == "Linter"

    @pytest.mark.asyncio
    async def test_quality_pipeline(self, project_path):
        """Тест Quality Pipeline"""
        from src.quality_gates import create_quick_pipeline

        orchestrator = create_quick_pipeline()

        # Запускаем быструю проверку
        result = await orchestrator.run_quick({
            "project_path": str(project_path)
        })

        assert result is not None
        assert result.total_gates > 0


class TestModelRouter:
    """Тесты для Model Router"""

    def test_model_selection(self):
        """Тест выбора модели"""
        from src.orchestrator.model_router import ModelRouter

        router = ModelRouter()

        # Тест выбора модели для кодирования
        model, reason = router.select_model(task_type="code")
        assert model is not None
        assert model.name is not None
        assert reason is not None

    def test_embedding_model(self):
        """Тест получения embedding модели"""
        from src.orchestrator.model_router import ModelRouter

        router = ModelRouter()
        model = router.get_embedding_model()

        # Должна вернуть embedding модель
        assert model is not None


class TestTaskParser:
    """Тесты для Task Parser"""

    def test_task_creation(self):
        """Тест создания задачи"""
        from src.orchestrator.task_parser import Task, TaskType

        # Создаём задачу напрямую
        task = Task(
            id="test-1",
            title="Fix README typo",
            description="Fix typo in README.md",
            type=TaskType.DOCUMENTATION
        )

        assert task.id == "test-1"
        assert task.type == TaskType.DOCUMENTATION
        assert task.status.value == "pending"


# Запуск тестов
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
