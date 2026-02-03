"""
Model Router

Выбирает оптимальную модель для каждой задачи.
Учитывает: тип задачи, сложность, доступную RAM, загруженные модели.
"""

import subprocess
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple
import httpx
import psutil


class ModelTier(Enum):
    """Уровни моделей по производительности"""
    FAST = "fast"          # <8B параметров, мгновенные ответы
    BALANCED = "balanced"  # 14-32B, хороший баланс
    POWERFUL = "powerful"  # 70B+, максимальное качество


@dataclass
class ModelConfig:
    """Конфигурация модели"""
    name: str
    provider: str = "ollama"
    tier: ModelTier = ModelTier.BALANCED
    ram_gb: float = 0
    context_window: int = 32768

    # Специализации
    strengths: List[str] = field(default_factory=list)

    # Производительность
    tokens_per_second: float = 40.0
    first_token_latency: float = 2.0

    # Статус
    is_loaded: bool = False

    def __post_init__(self):
        if not self.strengths:
            self.strengths = ["general"]


# Предопределённые модели
AVAILABLE_MODELS: Dict[str, ModelConfig] = {
    # Fast tier
    "qwen3:8b": ModelConfig(
        name="qwen3:8b",
        tier=ModelTier.FAST,
        ram_gb=5.2,
        strengths=["classification", "summarization", "quick_tasks"],
        tokens_per_second=80,
        first_token_latency=0.5
    ),

    # Balanced tier - Coding
    "qwen3-coder:30b": ModelConfig(
        name="qwen3-coder:30b",
        tier=ModelTier.BALANCED,
        ram_gb=18,
        context_window=32768,
        strengths=["implementation", "refactoring", "testing", "debugging"],
        tokens_per_second=50,
        first_token_latency=1.5
    ),
    "deepseek-coder:33b-instruct": ModelConfig(
        name="deepseek-coder:33b-instruct",
        tier=ModelTier.BALANCED,
        ram_gb=18,
        strengths=["implementation", "code_generation"],
        tokens_per_second=45,
        first_token_latency=2.0
    ),
    "codestral:latest": ModelConfig(
        name="codestral:latest",
        tier=ModelTier.BALANCED,
        ram_gb=12,
        strengths=["fim", "autocomplete", "snippets"],
        tokens_per_second=55,
        first_token_latency=1.0
    ),
    "devstral": ModelConfig(
        name="devstral",
        tier=ModelTier.BALANCED,
        ram_gb=14,
        strengths=["agentic", "swe_tasks", "multi_step"],
        tokens_per_second=45,
        first_token_latency=1.5
    ),

    # Balanced tier - Reasoning
    "deepseek-r1:32b": ModelConfig(
        name="deepseek-r1:32b",
        tier=ModelTier.BALANCED,
        ram_gb=19,
        strengths=["architecture", "review", "reasoning", "debugging", "planning"],
        tokens_per_second=35,
        first_token_latency=2.5
    ),
    "codellama:34b": ModelConfig(
        name="codellama:34b",
        tier=ModelTier.BALANCED,
        ram_gb=19,
        strengths=["review", "analysis", "code_understanding"],
        tokens_per_second=40,
        first_token_latency=2.0
    ),

    # Powerful tier
    "llama3.3:latest": ModelConfig(
        name="llama3.3:latest",
        tier=ModelTier.POWERFUL,
        ram_gb=42,
        context_window=131072,
        strengths=["general", "long_context", "complex_tasks"],
        tokens_per_second=25,
        first_token_latency=3.0
    ),
    "llama3:70b": ModelConfig(
        name="llama3:70b",
        tier=ModelTier.POWERFUL,
        ram_gb=39,
        strengths=["complex_reasoning", "fallback"],
        tokens_per_second=20,
        first_token_latency=4.0
    ),

    # Embedding models
    "nomic-embed-text": ModelConfig(
        name="nomic-embed-text",
        tier=ModelTier.FAST,
        ram_gb=0.3,
        strengths=["embeddings", "semantic_search"],
        tokens_per_second=300,
        first_token_latency=0.01
    ),
    "qwen3-embedding:8b": ModelConfig(
        name="qwen3-embedding:8b",
        tier=ModelTier.BALANCED,
        ram_gb=4.7,
        strengths=["embeddings", "code_embeddings"],
        tokens_per_second=200,
        first_token_latency=0.05
    ),
}

# Маппинг задач на модели
TASK_MODEL_MAPPING = {
    # Тип задачи -> (primary_model, fallback_model)
    "architecture": ("deepseek-r1:32b", "llama3:70b"),
    "implementation": ("qwen3-coder:30b", "deepseek-coder:33b-instruct"),
    "refactoring": ("qwen3-coder:30b", "deepseek-r1:32b"),
    "bugfix": ("qwen3-coder:30b", "deepseek-r1:32b"),
    "testing": ("qwen3-coder:30b", "devstral"),
    "review": ("deepseek-r1:32b", "codellama:34b"),
    "documentation": ("qwen3:8b", "qwen3-coder:30b"),
    "devops": ("qwen3-coder:30b", "deepseek-r1:32b"),
    "research": ("deepseek-r1:32b", "llama3.3:latest"),
    "agentic": ("devstral", "qwen3-coder:30b"),
    "fim": ("codestral:latest", "qwen3-coder:30b"),
    "quick": ("qwen3:8b", "qwen3-coder:30b"),
    "embedding": ("nomic-embed-text", "qwen3-embedding:8b"),
}


class ModelRouter:
    """
    Роутер для выбора оптимальной модели
    """

    def __init__(
        self,
        ollama_url: str = "http://localhost:11434",
        max_ram_gb: float = 98.0,  # 128 - 30 (OS + services)
        prefer_speed: bool = False
    ):
        self.ollama_url = ollama_url
        self.max_ram_gb = max_ram_gb
        self.prefer_speed = prefer_speed
        self.client = httpx.Client(timeout=30.0)

        self.models = AVAILABLE_MODELS.copy()
        self.loaded_models: Dict[str, ModelConfig] = {}

        # Обновить список доступных моделей
        self._refresh_available_models()

    def _refresh_available_models(self) -> None:
        """Обновить список моделей из Ollama"""
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")[1:]  # Skip header

                available = set()
                for line in lines:
                    if line.strip():
                        name = line.split()[0]
                        available.add(name)

                # Обновить статус моделей
                for model_name in self.models:
                    if model_name in available or model_name.split(":")[0] in available:
                        self.models[model_name].is_loaded = True

        except Exception as e:
            print(f"Warning: Could not refresh models: {e}")

    def _get_available_ram(self) -> float:
        """Получить доступную RAM в GB"""
        mem = psutil.virtual_memory()
        available_gb = mem.available / (1024 ** 3)
        return min(available_gb, self.max_ram_gb)

    def _get_loaded_ram(self) -> float:
        """Получить RAM, используемую загруженными моделями"""
        return sum(m.ram_gb for m in self.loaded_models.values())

    def select_model(
        self,
        task_type: str,
        complexity: str = "medium",
        context_size: int = 0,
        force_model: Optional[str] = None
    ) -> Tuple[ModelConfig, str]:
        """
        Выбрать оптимальную модель для задачи

        Args:
            task_type: Тип задачи (architecture, implementation, etc.)
            complexity: Сложность (simple, medium, complex)
            context_size: Примерный размер контекста в токенах
            force_model: Принудительно использовать эту модель

        Returns:
            Tuple[ModelConfig, str]: (конфиг модели, причина выбора)
        """
        # Принудительный выбор
        if force_model and force_model in self.models:
            return self.models[force_model], f"Forced: {force_model}"

        # Получить рекомендуемые модели для типа задачи
        primary, fallback = TASK_MODEL_MAPPING.get(
            task_type,
            ("qwen3-coder:30b", "deepseek-r1:32b")
        )

        # Проверить доступность primary модели
        primary_config = self.models.get(primary)
        if not primary_config:
            primary_config = self.models.get(fallback, list(self.models.values())[0])

        # Проверить RAM
        available_ram = self._get_available_ram()

        # Если сложная задача и есть RAM — используем мощную модель
        if complexity == "complex" and available_ram > 40:
            # Попробовать более мощную модель
            if task_type in ["architecture", "research", "review"]:
                if "llama3:70b" in self.models and available_ram > 40:
                    return self.models["llama3:70b"], "Complex task, using powerful model"

        # Если простая задача или prefer_speed — используем быструю
        if complexity == "simple" or self.prefer_speed:
            fast_models = [m for m in self.models.values() if m.tier == ModelTier.FAST]
            if fast_models:
                return fast_models[0], "Simple task, using fast model"

        # Проверить контекст
        if context_size > 32000 and "llama3.3:latest" in self.models:
            return self.models["llama3.3:latest"], "Large context, using 128K model"

        # Вернуть primary модель
        reason = f"Best fit for {task_type}"
        return primary_config, reason

    def get_embedding_model(self) -> ModelConfig:
        """Получить модель для embeddings"""
        if "nomic-embed-text" in self.models:
            return self.models["nomic-embed-text"]
        return self.models.get("qwen3-embedding:8b", list(self.models.values())[0])

    def can_load_model(self, model_name: str) -> Tuple[bool, str]:
        """
        Проверить, можно ли загрузить модель

        Returns:
            Tuple[bool, str]: (можно ли загрузить, причина)
        """
        model = self.models.get(model_name)
        if not model:
            return False, f"Model {model_name} not found"

        available_ram = self._get_available_ram()
        loaded_ram = self._get_loaded_ram()

        # Уже загружена?
        if model_name in self.loaded_models:
            return True, "Already loaded"

        # Хватает RAM?
        if loaded_ram + model.ram_gb <= available_ram:
            return True, "Sufficient RAM"

        # Нужно выгрузить другие модели
        return False, f"Need to unload models (need {model.ram_gb}GB, available {available_ram - loaded_ram}GB)"

    def suggest_unload(self, needed_ram: float) -> List[str]:
        """
        Предложить модели для выгрузки

        Returns:
            Список моделей, которые можно выгрузить
        """
        # Сортируем по "ненужности": давно не использовались, большие
        candidates = []

        for name, model in self.loaded_models.items():
            if model.tier == ModelTier.FAST:
                # Быстрые модели держим
                continue
            candidates.append((name, model.ram_gb))

        # Сортируем по размеру (сначала большие)
        candidates.sort(key=lambda x: -x[1])

        to_unload = []
        freed = 0
        for name, ram in candidates:
            to_unload.append(name)
            freed += ram
            if freed >= needed_ram:
                break

        return to_unload

    def get_model_info(self, model_name: str) -> Optional[dict]:
        """Получить информацию о модели"""
        model = self.models.get(model_name)
        if not model:
            return None

        return {
            "name": model.name,
            "tier": model.tier.value,
            "ram_gb": model.ram_gb,
            "context_window": model.context_window,
            "strengths": model.strengths,
            "tokens_per_second": model.tokens_per_second,
            "is_loaded": model.is_loaded,
        }

    def get_status(self) -> dict:
        """Получить статус роутера"""
        available_ram = self._get_available_ram()
        loaded_ram = self._get_loaded_ram()

        return {
            "total_models": len(self.models),
            "loaded_models": list(self.loaded_models.keys()),
            "available_ram_gb": round(available_ram, 1),
            "loaded_ram_gb": round(loaded_ram, 1),
            "can_load_more": available_ram - loaded_ram > 5,
        }


# CLI для тестирования
if __name__ == "__main__":
    router = ModelRouter()

    print("📊 Model Router Status")
    print("=" * 50)

    status = router.get_status()
    print(f"Total models: {status['total_models']}")
    print(f"Available RAM: {status['available_ram_gb']} GB")

    print("\n🔍 Task → Model Mapping:")
    for task_type in ["architecture", "implementation", "review", "testing", "documentation"]:
        model, reason = router.select_model(task_type)
        print(f"  {task_type:15} → {model.name:25} ({reason})")

    print("\n📦 Available Models:")
    for name, model in router.models.items():
        status_icon = "✅" if model.is_loaded else "⬜"
        print(f"  {status_icon} {name:25} {model.ram_gb:5.1f}GB  {model.tier.value:10}  {model.strengths[:2]}")
