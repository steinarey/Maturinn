"""LangChain implementation of LLMProvider: Anthropic, OpenAI or Gemini."""
import base64
import json
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.config import Settings
from app.services.llm.base import (
    Image, LLMError, StopRun, ToolCall, ToolError, ToolHandler, ToolSpec,
)

# Stop reasons that mean the reply is unusable, across providers.
_BAD_STOPS = {"refusal", "max_tokens", "length", "content_filter", "SAFETY", "MAX_TOKENS"}


def normalize_model(provider: str, name: str) -> str:
    """Accept friendly Anthropic names: 'haiku-5.5' -> 'claude-haiku-5-5'."""
    name = name.strip()
    if provider == "anthropic" and not name.startswith("claude-"):
        name = "claude-" + name
    if provider == "anthropic":
        name = re.sub(r"(\d)\.(\d)", r"\1-\2", name)
    return name


def make_chat_model(settings: Settings) -> BaseChatModel:
    provider, key = settings.provider, settings.provider_key()
    model = normalize_model(provider, settings.llm or "")
    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, anthropic_api_key=key, max_tokens=16000, max_retries=2)
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, openai_api_key=key, max_retries=2)
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model, google_api_key=key, max_retries=2)
    raise LLMError(f"unknown provider {provider!r}")


class LangChainLLM:
    def __init__(self, chat: BaseChatModel):
        self.chat = chat

    def run_tools(self, system: str, user: str, tools: list[ToolSpec],
                  handler: ToolHandler, max_rounds: int = 25, images: list[Image] | None = None) -> None:
        model = self.chat.bind_tools([
            {"type": "function", "function": {"name": t.name, "description": t.description,
                                              "parameters": t.parameters}}
            for t in tools
        ])
        if images:
            # LangChain standard content blocks; each provider package converts them.
            content = [{"type": "image", "base64": base64.b64encode(i.data).decode("ascii"),
                        "mime_type": i.mime_type} for i in images]
            human = HumanMessage(content=[*content, {"type": "text", "text": user}])
        else:
            human = HumanMessage(user)
        messages = [SystemMessage(system), human]
        for _ in range(max_rounds):
            try:
                ai = model.invoke(messages)
            except Exception as e:  # provider SDK errors differ; report uniformly
                raise LLMError(f"{type(e).__name__}: {e}") from e
            meta = ai.response_metadata or {}
            stop = meta.get("stop_reason") or meta.get("finish_reason")
            if stop in _BAD_STOPS:
                raise LLMError(f"model stopped: {stop}")
            messages.append(ai)  # append unchanged; providers may need their own blocks back

            results = []
            for bad in ai.invalid_tool_calls:
                results.append(ToolMessage(f"Error: could not parse arguments: {bad.get('error')}",
                                           tool_call_id=bad.get("id") or "", status="error"))
            if not ai.tool_calls and not results:
                return
            stop_run = None
            for tc in ai.tool_calls:
                call = ToolCall(id=tc["id"], name=tc["name"], args=tc.get("args") or {})
                try:
                    out = handler(call)
                    results.append(ToolMessage(out, tool_call_id=call.id))
                except ToolError as e:
                    results.append(ToolMessage(f"Error: {e}", tool_call_id=call.id, status="error"))
                except StopRun as e:
                    stop_run = e
                    results.append(ToolMessage("Stopped.", tool_call_id=call.id))
            if stop_run:
                raise stop_run
            messages.extend(results)
        raise LLMError(f"no result after {max_rounds} rounds")


def get_llm(settings: Settings) -> LangChainLLM | None:
    if not settings.llm_configured:
        return None
    return LangChainLLM(make_chat_model(settings))


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)
