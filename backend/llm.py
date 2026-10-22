"""LLM client for any OpenAI-compatible endpoint (OpenAI now, on-premise Qwen later).

Every call asks for JSON, validates it against a Pydantic model and retries once
with the validation error if the model's output does not fit.
"""

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from .config import settings
from .prompts import SYSTEM

T = TypeVar("T", bound=BaseModel)


class LLMError(RuntimeError):
    pass


@dataclass
class Usage:
    """Accumulates cost and latency across the calls of one request."""
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    retries: int = 0
    model: str = field(default_factory=lambda: settings.llm_model)

    def as_dict(self) -> dict:
        return {"model": self.model, "provider": settings.llm_provider, "calls": self.calls,
                "prompt_tokens": self.prompt_tokens, "completion_tokens": self.completion_tokens,
                "latency_ms": self.latency_ms, "retries": self.retries}


_client: AsyncOpenAI | None = None
_semaphore = asyncio.Semaphore(settings.llm_max_concurrency)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.llm_api_key:
            raise LLMError("LLM_API_KEY (or OPENAI_API_KEY) is not set. Set it, or use LLM_PROVIDER=mock.")
        _client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url,
                              timeout=settings.llm_timeout_s)
    return _client


def _parse_json(text: str) -> dict:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in the response")
    return json.loads(text[start:end + 1])


async def json_call(prompt: str, schema: type[T], usage: Usage, temperature: float = 0.2) -> T:
    if settings.llm_provider == "mock":
        usage.calls += 1
        return schema.model_validate(_mock_answer(prompt, schema))

    messages = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": prompt}]
    last_error = ""
    for attempt in range(2):
        kwargs = {"model": settings.llm_model, "messages": messages, "temperature": temperature}
        if settings.llm_json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        started = time.perf_counter()
        try:
            async with _semaphore:
                resp = await _get_client().chat.completions.create(**kwargs)
        except Exception as exc:  # network, auth, rate limit, timeout
            raise LLMError(f"LLM call failed: {type(exc).__name__}: {exc}") from exc
        usage.calls += 1
        usage.latency_ms += int((time.perf_counter() - started) * 1000)
        if resp.usage:
            usage.prompt_tokens += resp.usage.prompt_tokens or 0
            usage.completion_tokens += resp.usage.completion_tokens or 0
        content = resp.choices[0].message.content or ""
        try:
            return schema.model_validate(_parse_json(content))
        except (ValueError, ValidationError) as exc:
            last_error = str(exc)[:800]
            usage.retries += attempt == 0
            messages += [
                {"role": "assistant", "content": content},
                {"role": "user", "content": f"That JSON did not match the schema: {last_error}\n"
                                            "Reply again with only the corrected JSON object."},
            ]
    raise LLMError(f"Model output did not match the schema after a retry: {last_error}")


# ---- Mock provider: deterministic answers for demos and tests ------------------

def _mock_answer(prompt: str, schema: type[BaseModel]) -> dict:
    name = schema.__name__
    titles = re.findall(r"\[Slide (\d+)\] (.+)", prompt)
    if name == "DeckSummary":
        nums = [int(n) for n, _ in titles] or [1]
        return {
            "executive_summary": f"(Mock) This {len(nums)}-slide deck covers: "
                                 + "; ".join(t for _, t in titles[:4]) + ".",
            "key_points": [{"text": f"(Mock) Slide {n} discusses {t}.", "slides": [int(n)]}
                           for n, t in titles[:6]],
            "decisions": [], "action_items": [],
            "open_questions": [{"text": "(Mock) Run with a real model to get a real summary.",
                                "slides": nums[:1]}],
        }
    if name == "_NotesOnly":
        title = titles[0][1] if titles else "this slide"
        words = re.search(r"about (\d+) words", prompt)
        return {"notes": f"(Mock, ~{words.group(1) if words else '?'} words requested) "
                         f"On this slide, I'll walk you through {title}."}
    if name == "Outline":
        count = int(re.search(r"excluding the title slide\): (\d+)", prompt).group(1))
        topic = re.search(r"Request: (.+)", prompt).group(1).strip()[:60]
        slides = [{"layout": "section", "title": "Overview", "bullets": [], "notes": "(Mock) Introduce the topic."}]
        slides += [{"layout": "bullets", "title": f"Point {i}",
                    "bullets": [f"(Mock) Key message {i}.1", f"(Mock) Key message {i}.2", "[figure]"],
                    "notes": f"(Mock) Explain point {i}."} for i in range(1, count)]
        return {"title": topic, "subtitle": "(Mock outline)", "slides": slides}
    raise LLMError(f"No mock answer for {name}")
