"""Deterministic provider for tests and for running without an API key."""
from collections.abc import Iterator
from typing import Any

from app.services.llm.base import Message


class FakeLLM:
    def __init__(self, json_reply: dict[str, Any] | None = None, chat_reply: str = "ok"):
        self.json_reply = json_reply or {}
        self.chat_reply = chat_reply
        self.calls: list[tuple[str, Any]] = []

    def complete_json(self, system: str, prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(("complete_json", prompt))
        return self.json_reply

    def stream_chat(self, system: str, messages: list[Message]) -> Iterator[str]:
        self.calls.append(("stream_chat", messages))
        yield from self.chat_reply.split(" ")
