"""LLM provider interface. Import, translation and the cooking guide (later
phases) depend only on this protocol, so the provider can be swapped."""
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str


class LLMProvider(Protocol):
    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        """Return an object matching `schema` (structured extraction / translation)."""
        ...

    def stream_chat(self, system: str, messages: list[Message]) -> Iterator[str]:
        """Yield text chunks of the assistant's reply."""
        ...
