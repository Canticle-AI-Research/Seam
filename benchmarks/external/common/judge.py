from __future__ import annotations

import io
import json
import os
import time
from dataclasses import dataclass
from typing import Protocol

# Constant polling interval for batch jobs. Anthropic / OpenAI batches run for
# minutes-to-hours; exponential backoff buys nothing here.
JUDGE_BATCH_POLL_SECONDS = 30
# Hard upper bound shared by both providers (Anthropic + OpenAI batch limits).
JUDGE_BATCH_MAX_REQUESTS = 100_000

DEFAULT_JUDGE_PROMPT = """You are an impartial scorer for a memory-benchmark question.

Question: {question}
Gold answer: {gold}
System answer: {pred}

Score the system answer:
- "correct" if it conveys the same meaning as the gold answer (paraphrasing is fine)
- "partial" if it contains the right entity/fact but is incomplete or has minor errors
- "incorrect" if it is wrong, unsupported, or empty

Respond ONLY with strict JSON in this exact shape:
{{"verdict": "correct" | "partial" | "incorrect", "rationale": "one short sentence"}}"""

ABSTAINING_JUDGE_PROMPT = """You are an impartial scorer for a memory-benchmark question.

Question: {question}
Gold answer: {gold}
System answer: {pred}

Score the system answer:
- "correct" if it conveys the same meaning as the gold answer (paraphrasing is fine)
- "partial" if it contains the right entity/fact but is incomplete or has minor errors
- "incorrect" if it is wrong or unsupported by the context
- If the system answer is exactly "unknown", score as "abstain" — neither correct nor incorrect.

Respond ONLY with strict JSON in this exact shape:
{{"verdict": "correct" | "partial" | "incorrect" | "abstain", "rationale": "one short sentence"}}"""


@dataclass(frozen=True)
class JudgeVerdict:
    verdict: str           # "correct" | "partial" | "incorrect" | "abstain"
    score: float           # 1.0 / 0.5 / 0.0 (abstain: 0.0)
    rationale: str
    judge_name: str
    judge_model: str


@dataclass(frozen=True)
class JudgeBatchItem:
    custom_id: str
    question: str
    gold: str
    pred: str


class Judge(Protocol):
    name: str
    model: str
    def score(self, *, question: str, gold: str, pred: str) -> JudgeVerdict: ...
    # Optional batch scoring via the provider's Message Batches / Batch API
    # (50% discount, async). When present, the runner can defer all judge
    # calls to one async batch instead of per-case sync requests.
    # def score_batch(self, items: list[JudgeBatchItem]) -> dict[str, JudgeVerdict | Exception]: ...


class StubJudge:
    """Deterministic smoke-test judge that never claims correctness."""
    name = "stub-informational-only"
    model = "stub-1"
    def score(self, *, question, gold, pred) -> JudgeVerdict:
        return JudgeVerdict("abstain", 0.0, "stub does not score correctness", self.name, self.model)


def _strip_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(line for line in lines if not line.startswith("```"))
    return text.strip()


def _verdict_from_json_text(text: str, *, judge_name: str, judge_model: str) -> JudgeVerdict:
    try:
        data = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError as exc:
        raise ValueError("judge returned unparseable JSON") from exc
    verdict = data.get("verdict")
    score_map = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0, "abstain": 0.0}
    if verdict not in score_map:
        raise ValueError("judge returned invalid verdict")
    rationale = str(data.get("rationale") or "judge returned no rationale")
    return JudgeVerdict(verdict, score_map[verdict], rationale, judge_name, judge_model)


class ClaudeJudge:
    name = "claude"

    def __init__(self, model: str | None = None):
        model = model or os.environ.get("SEAM_BENCH_JUDGE_MODEL", "claude-haiku-4-5-20251001")
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError(
                "--judge claude requires the anthropic package. "
                "Install with: pip install seam[bench-judge]"
            ) from exc
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("--judge claude requires ANTHROPIC_API_KEY in the environment")
        self.model = model
        self._client = Anthropic(api_key=api_key)

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        prompt = DEFAULT_JUDGE_PROMPT.format(question=question, gold=gold, pred=pred)
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise RuntimeError(f"judge request failed: {type(exc).__name__}") from exc
        return _verdict_from_json_text(response.content[0].text, judge_name=self.name, judge_model=self.model)

    def score_batch(
        self,
        items: list[JudgeBatchItem],
        *,
        poll_seconds: float = JUDGE_BATCH_POLL_SECONDS,
    ) -> dict[str, JudgeVerdict | Exception]:
        """Submit all items as one Anthropic Message Batches job (50% discount).

        Returns a mapping ``custom_id -> JudgeVerdict | Exception``. Caller is
        responsible for placing the verdicts back into per-case report rows.
        """
        if not items:
            return {}
        if len(items) > JUDGE_BATCH_MAX_REQUESTS:
            raise ValueError(
                f"batch exceeds provider limit: {len(items)} > {JUDGE_BATCH_MAX_REQUESTS}"
            )
        seen_ids: set[str] = set()
        requests_payload: list[dict] = []
        for item in items:
            if item.custom_id in seen_ids:
                raise ValueError(f"duplicate custom_id in batch: {item.custom_id!r}")
            seen_ids.add(item.custom_id)
            prompt = DEFAULT_JUDGE_PROMPT.format(
                question=item.question, gold=item.gold, pred=item.pred
            )
            requests_payload.append(
                {
                    "custom_id": item.custom_id,
                    "params": {
                        "model": self.model,
                        "max_tokens": 256,
                        "messages": [{"role": "user", "content": prompt}],
                    },
                }
            )

        batch = self._client.messages.batches.create(requests=requests_payload)
        batch_id = batch.id
        while True:
            current = self._client.messages.batches.retrieve(batch_id)
            status = getattr(current, "processing_status", None)
            if status == "ended":
                break
            if status in {"canceling", "canceled"}:
                raise RuntimeError(f"judge batch ended with status {status!r}")
            time.sleep(poll_seconds)

        results: dict[str, JudgeVerdict | Exception] = {}
        for entry in self._client.messages.batches.results(batch_id):
            custom_id = getattr(entry, "custom_id", None)
            if custom_id is None:
                continue
            result_obj = getattr(entry, "result", None)
            result_type = getattr(result_obj, "type", None)
            if result_type == "succeeded":
                message = getattr(result_obj, "message", None)
                content = getattr(message, "content", None) or []
                text = ""
                for block in content:
                    btext = getattr(block, "text", None)
                    if isinstance(btext, str):
                        text = btext
                        break
                try:
                    results[custom_id] = _verdict_from_json_text(
                        text, judge_name=self.name, judge_model=self.model
                    )
                except ValueError as exc:
                    results[custom_id] = exc
            else:
                error_obj = getattr(result_obj, "error", None)
                msg = getattr(error_obj, "message", None) or f"batch result {result_type!r}"
                results[custom_id] = RuntimeError(f"judge batch entry failed: {msg}")
        for item in items:
            results.setdefault(
                item.custom_id, RuntimeError("judge batch returned no entry for custom_id")
            )
        return results


def _openai_judge_reasoning_params() -> tuple[int, str]:
    """Completion budget + reasoning effort for gpt-5/o-series judges.

    ``reasoning_effort="minimal"`` is rejected by gpt-5.4+ models (which support
    only none/low/medium/high/xhigh), so mirror the answerer fix (HISTORY#321):
    read both from the env with a broadly-supported default of "low". The budget
    is floored so reasoning tokens do not starve the required JSON verdict.
    """
    budget = int(os.environ.get("SEAM_BENCH_JUDGE_MAX_COMPLETION_TOKENS", "512"))
    effort = os.environ.get(
        "SEAM_BENCH_JUDGE_REASONING_EFFORT",
        os.environ.get("SEAM_BENCH_REASONING_EFFORT", "low"),
    )
    return budget, effort


class OpenAIJudge:
    name = "openai"

    def __init__(self, model: str | None = None):
        model = model or os.environ.get("SEAM_BENCH_JUDGE_MODEL", "gpt-4o-mini")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError(
                "--judge openai requires the openai package. "
                "Install with: pip install seam[bench-judge]"
            ) from exc
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("--judge openai requires OPENAI_API_KEY in the environment")
        self.model = model
        self._client = OpenAI(api_key=api_key)

    @staticmethod
    def _uses_completion_token_budget(model: str) -> bool:
        model_id = model.lower()
        return model_id.startswith(("gpt-5", "o1", "o3", "o4"))

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        prompt = DEFAULT_JUDGE_PROMPT.format(question=question, gold=gold, pred=pred)
        try:
            request = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
            }
            if self._uses_completion_token_budget(self.model):
                # GPT-5/o-series models reject max_tokens and can spend part of the
                # budget on hidden reasoning tokens. Effort/budget are env-driven
                # (default "low") because gpt-5.4+ reject the former "minimal".
                budget, effort = _openai_judge_reasoning_params()
                request["max_completion_tokens"] = budget
                request["reasoning_effort"] = effort
            else:
                request["max_tokens"] = 256
            response = self._client.chat.completions.create(
                **request,
            )
        except Exception as exc:
            raise RuntimeError(f"judge request failed: {type(exc).__name__}") from exc
        text = response.choices[0].message.content or ""
        return _verdict_from_json_text(text, judge_name=self.name, judge_model=self.model)

    def _build_batch_request(self, item: JudgeBatchItem) -> dict:
        prompt = DEFAULT_JUDGE_PROMPT.format(
            question=item.question, gold=item.gold, pred=item.pred
        )
        body: dict = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        }
        if self._uses_completion_token_budget(self.model):
            budget, effort = _openai_judge_reasoning_params()
            body["max_completion_tokens"] = budget
            body["reasoning_effort"] = effort
        else:
            body["max_tokens"] = 256
        return {
            "custom_id": item.custom_id,
            "method": "POST",
            "url": "/v1/chat/completions",
            "body": body,
        }

    def score_batch(
        self,
        items: list[JudgeBatchItem],
        *,
        poll_seconds: float = JUDGE_BATCH_POLL_SECONDS,
    ) -> dict[str, JudgeVerdict | Exception]:
        """Submit all items as one OpenAI Batch API job (50% discount).

        Uploads a JSONL of chat-completion requests, creates the batch, polls
        until terminal, downloads the output file, and parses verdicts. Returns
        a mapping ``custom_id -> JudgeVerdict | Exception``.
        """
        if not items:
            return {}
        if len(items) > JUDGE_BATCH_MAX_REQUESTS:
            raise ValueError(
                f"batch exceeds provider limit: {len(items)} > {JUDGE_BATCH_MAX_REQUESTS}"
            )
        batches_api = getattr(self._client, "batches", None)
        files_api = getattr(self._client, "files", None)
        if batches_api is None or files_api is None:
            raise RuntimeError(
                "OpenAIJudge.score_batch requires openai>=1.13 with Batch API support"
            )

        seen_ids: set[str] = set()
        jsonl_lines: list[str] = []
        for item in items:
            if item.custom_id in seen_ids:
                raise ValueError(f"duplicate custom_id in batch: {item.custom_id!r}")
            seen_ids.add(item.custom_id)
            jsonl_lines.append(json.dumps(self._build_batch_request(item)))
        jsonl_blob = ("\n".join(jsonl_lines) + "\n").encode("utf-8")
        upload = files_api.create(
            file=("judge-batch.jsonl", io.BytesIO(jsonl_blob)),
            purpose="batch",
        )
        batch = batches_api.create(
            input_file_id=upload.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
        )
        batch_id = batch.id
        while True:
            current = batches_api.retrieve(batch_id)
            status = getattr(current, "status", None)
            if status == "completed":
                output_file_id = getattr(current, "output_file_id", None)
                error_file_id = getattr(current, "error_file_id", None)
                break
            if status in {"failed", "expired", "cancelled", "cancelling"}:
                raise RuntimeError(f"judge batch ended with status {status!r}")
            time.sleep(poll_seconds)

        results: dict[str, JudgeVerdict | Exception] = {}
        if output_file_id:
            output_blob = files_api.content(output_file_id)
            text_blob = _decode_file_content(output_blob)
            for line in text_blob.splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                custom_id = entry.get("custom_id")
                if not custom_id:
                    continue
                response = entry.get("response") or {}
                body = response.get("body") or {}
                status_code = response.get("status_code")
                error = entry.get("error")
                if error or (status_code is not None and status_code >= 400):
                    msg = (error or {}).get("message") if isinstance(error, dict) else str(error)
                    results[custom_id] = RuntimeError(
                        f"judge batch entry failed: {msg or status_code!r}"
                    )
                    continue
                choices = body.get("choices") or []
                text = ""
                if choices:
                    message = choices[0].get("message") or {}
                    text = message.get("content") or ""
                try:
                    results[custom_id] = _verdict_from_json_text(
                        text, judge_name=self.name, judge_model=self.model
                    )
                except ValueError as exc:
                    results[custom_id] = exc
        if error_file_id:
            error_blob = files_api.content(error_file_id)
            text_blob = _decode_file_content(error_blob)
            for line in text_blob.splitlines():
                if not line.strip():
                    continue
                entry = json.loads(line)
                custom_id = entry.get("custom_id")
                if not custom_id:
                    continue
                err = entry.get("error") or {}
                msg = err.get("message") if isinstance(err, dict) else str(err)
                results[custom_id] = RuntimeError(f"judge batch entry failed: {msg!r}")
        for item in items:
            results.setdefault(
                item.custom_id, RuntimeError("judge batch returned no entry for custom_id")
            )
        return results


def _decode_file_content(blob) -> str:
    """Normalize the openai files.content() return value to text."""
    if isinstance(blob, str):
        return blob
    if isinstance(blob, bytes):
        return blob.decode("utf-8")
    text = getattr(blob, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(blob, "content", None)
    if isinstance(content, bytes):
        return content.decode("utf-8")
    if isinstance(content, str):
        return content
    read = getattr(blob, "read", None)
    if callable(read):
        data = read()
        if isinstance(data, bytes):
            return data.decode("utf-8")
        if isinstance(data, str):
            return data
    raise RuntimeError(f"cannot decode OpenAI file content of type {type(blob).__name__}")


def build_judge(name: str | None, model: str | None = None) -> Judge | None:
    if name is None or name == "none":
        return None
    if name == "stub":
        return StubJudge()
    if name == "claude":
        return ClaudeJudge(model=model)
    if name == "openai":
        return OpenAIJudge(model=model)
    raise ValueError(f"unknown judge: {name!r} (use stub|claude|openai|none)")
