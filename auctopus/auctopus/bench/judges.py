"""Judge-model clients for the benchmarks' own evaluators.

The evaluators are used unchanged (their rubrics, parsing and scoring stay the benchmark's); what differs is only how
the judge model is constructed:

- MLR-Bench builds judges through an allow-list of model names and passes `max_tokens` to Chat Completions, which
  gpt-5 models reject (`max_completion_tokens`). JudgeLLM / JudgeLMM subclass its OpenAI clients with that one fix.
- DiscoveryWorld's KnowledgeScorer has the same `max_tokens` argument; JudgeKnowledgeScorer overrides the one helper.
- ResearchClawBench's scorer reads JUDGE_API_KEY / JUDGE_API_BASE / JUDGE_MODEL_NAME; rcb_judge_env() sets them from
  the OpenAI key for an OpenAI judge model.
"""
from __future__ import annotations

import os
from typing import Any


def _needs_completion_tokens(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


def _fix_kwargs(model: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    if _needs_completion_tokens(model):
        if "max_tokens" in kwargs:
            kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
        kwargs.pop("temperature", None)       # reasoning models accept only the default temperature
    return kwargs


def mlr_text_judge(model: str, max_tokens: int = 16384):
    """An MLR-Bench LLM judge (review_idea, review_proposal, review_experiment) on any OpenAI chat model."""
    from mlrbench.llm.llm import OpenAILLM

    class JudgeLLM(OpenAILLM):
        def generate(self, prompt: str, **kwargs: Any):
            self.kwargs = _fix_kwargs(self.model_name, dict(self.kwargs))
            return super().generate(prompt, **_fix_kwargs(self.model_name, dict(kwargs)))

        def chat(self, chat, **kwargs: Any):
            self.kwargs = _fix_kwargs(self.model_name, dict(self.kwargs))
            return super().chat(chat, **_fix_kwargs(self.model_name, dict(kwargs)))

    return JudgeLLM(model_name=model, api_key=os.environ.get("OPENAI_API_KEY"), max_tokens=max_tokens)


def mlr_multimodal_judge(model: str, max_tokens: int = 16384):
    """An MLR-Bench LMM judge (review_writeup, eval_hallucination) on any OpenAI vision-capable chat model."""
    from mlrbench.lmm.lmm import OpenAILMM

    class JudgeLMM(OpenAILMM):
        def generate(self, prompt: str, media=None, **kwargs: Any):
            self.kwargs = _fix_kwargs(self.model_name, dict(self.kwargs))
            return super().generate(prompt, media=media, **_fix_kwargs(self.model_name, dict(kwargs)))

    return JudgeLMM(model_name=model, api_key=os.environ.get("OPENAI_API_KEY"), max_tokens=max_tokens)


def dw_knowledge_scorer(model: str):
    """DiscoveryWorld's KnowledgeScorer (scripts/knowledgeScorer.py) with the token argument fixed for gpt-5."""
    from knowledgeScorer import KnowledgeScorer

    class JudgeKnowledgeScorer(KnowledgeScorer):
        def OpenAIGetCompletionHelper(self, client, promptStr: str, model: str, temperature=0.0, maxTokens=800,
                                      jsonResponse: bool = False):
            messages = [{"role": "user", "content": [{"type": "text", "text": promptStr}]}]
            kwargs: dict[str, Any] = {"model": model, "messages": messages, "max_tokens": maxTokens,
                                      "temperature": temperature}
            if jsonResponse:
                kwargs["response_format"] = {"type": "json_object"}
            return client.chat.completions.create(**_fix_kwargs(model, kwargs))

    return JudgeKnowledgeScorer(model=model)


def rcb_judge_env(model: str) -> dict[str, str]:
    """Environment for ResearchClawBench's scorer: an OpenAI judge model through its OpenAI-compatible client."""
    key = os.environ.get("OPENAI_API_KEY", "")
    env = {"JUDGE_MODEL_NAME": os.environ.get("JUDGE_MODEL_NAME") or model,
           "JUDGE_API_BASE": os.environ.get("JUDGE_API_BASE") or "https://api.openai.com/v1",
           "JUDGE_API_KEY": os.environ.get("JUDGE_API_KEY") or key}
    os.environ.update(env)
    return env
