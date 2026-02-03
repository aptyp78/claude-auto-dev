"""
Quality Gates Module

Система контроля качества кода для Local Swarm.
Автоматические проверки с retry и эскалацией.
"""

from .base import (
    QualityGate,
    GateResult,
    GateIssue,
    GateSeverity,
)

from .test_runner import TestRunnerGate
from .linter import LinterGate
from .security_scanner import SecurityScannerGate
from .coverage_checker import CoverageCheckerGate

from .orchestrator import (
    QualityGateOrchestrator,
    PipelineResult,
    create_strict_pipeline,
    create_lenient_pipeline,
    create_quick_pipeline,
)

__all__ = [
    # Base
    "QualityGate",
    "GateResult",
    "GateIssue",
    "GateSeverity",
    # Gates
    "TestRunnerGate",
    "LinterGate",
    "SecurityScannerGate",
    "CoverageCheckerGate",
    # Orchestrator
    "QualityGateOrchestrator",
    "PipelineResult",
    # Factory functions
    "create_strict_pipeline",
    "create_lenient_pipeline",
    "create_quick_pipeline",
]
