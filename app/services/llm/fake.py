"""Scripted provider for tests: replays a fixed list of tool calls."""
from app.services.llm.base import StopRun, ToolCall, ToolError, ToolHandler, ToolSpec


class FakeLLM:
    def __init__(self, calls: list[tuple[str, dict]] | None = None):
        self.calls = calls or []
        self.results: list[str] = []
        self.prompts: list[tuple[str, str]] = []

    def run_tools(self, system: str, user: str, tools: list[ToolSpec],
                  handler: ToolHandler, max_rounds: int = 25) -> None:
        self.prompts.append((system, user))
        names = {t.name for t in tools}
        for i, (name, args) in enumerate(self.calls):
            assert name in names, f"unknown tool {name}"
            try:
                self.results.append(handler(ToolCall(id=f"call_{i}", name=name, args=args)))
            except ToolError as e:
                self.results.append(f"Error: {e}")
            except StopRun:
                raise
