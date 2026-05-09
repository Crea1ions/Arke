"""Task graph — core data structures for Arke kernel v0.1.

Defines the immutable contracts: StepStatus, Validation, Step, Task.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class StepStatus(Enum):
    """Lifecycle state of a single execution step."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class Validation:
    """Deterministic gate applied after a step executes.

    Args:
        type: One of ``'file_exists'``, ``'return_code'``, ``'json_schema'``.
        expected: The expected value to validate against.
    """

    type: str
    expected: Any


@dataclass
class Step:
    """Atomic execution unit inside a Task Graph.

    Args:
        id: Unique identifier within the task (e.g. ``'step_1'``).
        tool: Executor to use — ``'cli'``, ``'fs'``, ``'sqlite'``, ``'llm'`` or ``'mcp'``.
        arguments: Tool-specific parameters (command, path, prompt …).
        validation: Optional gate checked after execution.
        retry_count: How many retries have been attempted so far.
        max_retries: Maximum retries before marking the step FAILED.
        dependencies: IDs of steps that must succeed before this one.
        status: Current lifecycle state.
        output: Raw output captured after execution.
    """

    id: str
    tool: str
    arguments: dict[str, Any]
    validation: Validation | None = None
    retry_count: int = 0
    max_retries: int = 2
    dependencies: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    output: Any = None


@dataclass
class Task:
    """Execution graph representing a single user intention.

    Args:
        id: Unique identifier (UUID-like string).
        description: Original user intention text.
        steps: Ordered list of steps (dependency order is enforced at runtime).
        status: Aggregate lifecycle state.
        total_cost: Cumulative LLM cost in EUR.
        tokens_used: Cumulative token count.
    """

    id: str
    description: str
    steps: list[Step]
    status: StepStatus = StepStatus.PENDING
    total_cost: float = 0.0
    tokens_used: int = 0
