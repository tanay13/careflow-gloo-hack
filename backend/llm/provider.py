"""Model integration behind a small interface.

* MockLLMProvider     - deterministic reasoner; the demo never depends on Wi-Fi.
* OpenAICompatibleProvider - any /chat/completions endpoint (Gloo AI Studio,
  OpenAI, local vLLM, ...). Configured with LLM_API_KEY / LLM_BASE_URL / LLM_MODEL.
* FallbackProvider    - wraps the real provider; on any error/timeout/invalid
  JSON it falls back to the mock and records why.

Model output is always treated as a *proposal*: it is schema-validated and
then checked by deterministic code before anything happens.
"""
from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from agent import prompts
from agent.policies import P
from config import settings


def _est_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class LLMResult(dict):
    """dict payload with a `usage` attribute."""

    usage: dict[str, Any]


def _result(payload: dict, usage: dict) -> LLMResult:
    r = LLMResult(payload)
    r.usage = usage
    return r


class LLMProvider(ABC):
    name = "abstract"

    @abstractmethod
    def normalize(self, request_text: str, intake_form: dict) -> LLMResult: ...

    @abstractmethod
    def generate_plan(self, case: dict, context: dict, feedback: dict, prior: dict | None) -> LLMResult: ...

    @abstractmethod
    def verify_plan(self, plan: dict, context: dict) -> LLMResult: ...


def render_normalizer(request_text: str, intake_form: dict) -> str:
    return prompts.NORMALIZER_PROMPT.format(campuses=P()["campuses"], request_text=request_text,
                                            intake_form=json.dumps(intake_form))


def render_planner(case: dict, context: dict, feedback: dict, prior: dict | None) -> str:
    return prompts.PLANNER_PROMPT.format(case=json.dumps(case, default=str), context=json.dumps(context, default=str),
                                         feedback=json.dumps(feedback, default=str),
                                         prior=json.dumps(prior, default=str) if prior else "null")


def render_verifier(plan: dict, context: dict) -> str:
    return prompts.VERIFIER_PROMPT.format(plan=json.dumps(plan, default=str), context=json.dumps(context, default=str))


class MockLLMProvider(LLMProvider):
    """Deterministic reasoner. Token counts are *estimates* of what the same
    prompts would cost on a real model (shown as 'estimated' in the UI)."""

    name = "mock-deterministic"

    def _usage(self, prompt: str, output: dict, t0: float) -> dict:
        return {
            "provider": self.name, "model": "deterministic-reasoner", "prompt_version": prompts.PROMPT_VERSION,
            "input_tokens": _est_tokens(prompts.SYSTEM_PROMPT + prompt),
            "output_tokens": _est_tokens(json.dumps(output, default=str)),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "estimated": True,
        }

    def normalize(self, request_text: str, intake_form: dict) -> LLMResult:
        from agent.normalizer import deterministic_extract

        t0 = time.perf_counter()
        out = deterministic_extract(request_text, intake_form)
        return _result(out, self._usage(render_normalizer(request_text, intake_form), out, t0))

    def generate_plan(self, case: dict, context: dict, feedback: dict, prior: dict | None) -> LLMResult:
        from agent.mock_reasoner import deterministic_plan

        t0 = time.perf_counter()
        out = deterministic_plan(case, context, feedback, prior)
        return _result(out, self._usage(render_planner(case, context, feedback, prior), out, t0))

    def verify_plan(self, plan: dict, context: dict) -> LLMResult:
        t0 = time.perf_counter()
        out = {"status": "PASS", "reasons": [], "invalid_fields": []}
        return _result(out, self._usage(render_verifier(plan, context), out, t0))


class OpenAICompatibleProvider(LLMProvider):
    name = "openai-compatible"

    def __init__(self) -> None:
        if not (settings.llm_api_key and settings.llm_base_url and settings.llm_model):
            raise RuntimeError("LLM_API_KEY, LLM_BASE_URL and LLM_MODEL must be set")
        self.client = httpx.Client(base_url=settings.llm_base_url.rstrip("/"), timeout=settings.llm_timeout_s,
                                   headers={"Authorization": f"Bearer {settings.llm_api_key}"})

    def _chat(self, user_prompt: str) -> LLMResult:
        t0 = time.perf_counter()
        body = {
            "model": settings.llm_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": prompts.SYSTEM_PROMPT},
                         {"role": "user", "content": user_prompt}],
        }
        resp = self.client.post("/chat/completions", json=body)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        content = content.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
        payload = json.loads(content)
        u = data.get("usage") or {}
        return _result(payload, {
            "provider": self.name, "model": settings.llm_model, "prompt_version": prompts.PROMPT_VERSION,
            "input_tokens": u.get("prompt_tokens", _est_tokens(user_prompt)),
            "output_tokens": u.get("completion_tokens", _est_tokens(content)),
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1), "estimated": "usage" not in data,
        })

    def normalize(self, request_text, intake_form):
        return self._chat(render_normalizer(request_text, intake_form))

    def generate_plan(self, case, context, feedback, prior):
        return self._chat(render_planner(case, context, feedback, prior))

    def verify_plan(self, plan, context):
        return self._chat(render_verifier(plan, context))


class FallbackProvider(LLMProvider):
    """Real provider with automatic deterministic fallback (demo reliability)."""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider):
        self.primary, self.fallback = primary, fallback
        self.name = f"{primary.name}+fallback"
        self.last_fallback_reason: str | None = None

    def _try(self, method: str, *args):
        try:
            res = getattr(self.primary, method)(*args)
            self.last_fallback_reason = None
            return res
        except Exception as e:  # noqa: BLE001
            self.last_fallback_reason = f"{type(e).__name__}: {str(e)[:160]}"
            res = getattr(self.fallback, method)(*args)
            res.usage = {**res.usage, "fallback_reason": self.last_fallback_reason}
            return res

    def normalize(self, *a):
        return self._try("normalize", *a)

    def generate_plan(self, *a):
        return self._try("generate_plan", *a)

    def verify_plan(self, *a):
        return self._try("verify_plan", *a)


_provider: LLMProvider | None = None
_forced_mock = False


def get_provider() -> LLMProvider:
    global _provider
    if _forced_mock:
        return MockLLMProvider()
    if _provider is None:
        if settings.use_mock_llm:
            _provider = MockLLMProvider()
        else:
            try:
                _provider = FallbackProvider(OpenAICompatibleProvider(), MockLLMProvider())
            except Exception:  # noqa: BLE001 - misconfigured -> deterministic mode
                _provider = MockLLMProvider()
    return _provider


def force_mock(flag: bool) -> None:
    """Evals run deterministically regardless of env configuration."""
    global _forced_mock
    _forced_mock = flag


def provider_info() -> dict:
    p = get_provider()
    return {"provider": p.name, "model": settings.llm_model if not isinstance(p, MockLLMProvider) else "deterministic-reasoner",
            "use_mock_llm": isinstance(p, MockLLMProvider), "prompt_version": prompts.PROMPT_VERSION}
