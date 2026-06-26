from __future__ import annotations

from dataclasses import replace

# Single source of truth for the short-answer prompt. Held CONSTANT across every
# memory-system adapter so a SEAM-vs-mem0 (etc.) head-to-head varies ONLY the
# retrieved context, never the answerer. SeamLocomoAdapter._generate_answer
# builds its prompt from build_answer_prompt() for exactly this reason.
_ANSWER_PROMPT = (
    "Answer the question using ONLY the context. "
    "Return the best supported answer found in the context, even when "
    "the context also contains unrelated snippets. "
    "Say 'unknown' only when the context contains no answer candidate. "
    "Reply with the shortest possible answer, no preamble.\n\n"
    "Context:\n{context}\n\nQuestion: {question}\nAnswer:"
)


def build_answer_prompt(question: str, context: str) -> str:
    """The shared answerer prompt. Identical text for every adapter."""
    return _ANSWER_PROMPT.format(context=context, question=question)


def generate_short_answer(
    answerer: str,
    answerer_model: str | None,
    question: str,
    context: str,
    *,
    diag_out: dict | None = None,
) -> str:
    """Dispatch to a provider short-answer fn over (question, context).

    The provider fns live in the SEAM adapter and are imported lazily so this
    module carries no import-time dependency on it, and so tests that
    monkeypatch ``seam._openai_short_answer`` (etc.) are honored at call time.
    """
    prompt = build_answer_prompt(question, context)
    extra = {"diag_out": diag_out} if diag_out is not None else {}
    from benchmarks.external.locomo.adapters import seam as _seam

    if answerer == "openai":
        return _seam._openai_short_answer(answerer_model or "gpt-4o-mini", prompt, **extra)
    if answerer == "claude":
        return _seam._claude_short_answer(
            answerer_model or "claude-haiku-4-5-20251001", prompt, **extra
        )
    if answerer == "ollama":
        return _seam._ollama_short_answer(answerer_model or "qwen2.5:3b", prompt, **extra)
    raise ValueError(f"unknown answerer {answerer!r}")


class SharedAnswererAdapter:
    """Wrap a comparator adapter that returns ``generated_answer=None`` so the
    SAME answerer used for SEAM also generates its answer from its retrieved
    context.

    Without this, the runner scores a null-answer adapter (mem0/zep) on an empty
    prediction -> ~0 under the LLM judge, which is not a fair comparison: it
    measures whether the adapter generates an answer, not the quality of its
    memory. The wrapper holds the answerer constant so only the retrieved
    context (the memory layer under test) varies.

    Adapters that already generate their own answer pass through untouched.
    ``_generate`` is injectable for tests.
    """

    def __init__(self, inner, answerer: str, answerer_model: str | None = None, *, _generate=None):
        self._inner = inner
        self.name = inner.name
        self._answerer = answerer
        self._answerer_model = answerer_model
        self._generate = _generate or generate_short_answer

    def reset(self, scope_id: str) -> None:
        self._inner.reset(scope_id)

    def ingest_turn(self, scope_id: str, turn) -> None:
        self._inner.ingest_turn(scope_id, turn)

    def answer(self, scope_id: str, question: str):
        ans = self._inner.answer(scope_id, question)
        if ans.generated_answer is not None:
            return ans
        diag: dict = {}
        generated = self._generate(
            self._answerer, self._answerer_model, question, ans.retrieved_context, diag_out=diag
        )
        return replace(
            ans,
            generated_answer=generated,
            answerer_diagnostics=ans.answerer_diagnostics or (diag or None),
        )

    def close(self) -> None:
        close = getattr(self._inner, "close", None)
        if callable(close):
            close()
