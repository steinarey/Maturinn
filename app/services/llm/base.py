"""Provider-neutral LLM interface.

Features (import now; translation and the cooking guide later) depend only on
this module. The concrete implementation is LangChain-based and picks the
provider from settings (PROVIDER + LLM).
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments


@dataclass
class Image:
    data: bytes
    mime_type: str = "image/jpeg"


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


class StopRun(Exception):
    """Raised by a tool handler to end the run early (e.g. "not a recipe")."""


class ToolError(Exception):
    """Raised by a tool handler for bad arguments; sent back to the model as an error result."""


class LLMError(Exception):
    """The model failed: refusal, output cut off, too many rounds, provider error."""


ToolHandler = Callable[[ToolCall], str]


class LLMProvider(Protocol):
    def run_tools(self, system: str, user: str, tools: list[ToolSpec],
                  handler: ToolHandler, max_rounds: int = 25, images: list[Image] | None = None) -> None:
        """Let the model call tools until it stops. Each call goes through `handler`,
        whose return value is sent back as the tool result. `images` go with the user message."""
        ...
