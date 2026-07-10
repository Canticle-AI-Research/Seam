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

# judge/2 (PR 2, HISTORY#371 follow-up): fixes three documented judge errors --
# alias/abbreviation under-scoring ("LeBron" vs "LeBron James"), subset-phrase
# under-scoring ("the Lord of the Rings trilogy" vs gold "Lord of the Rings"),
# and penalizing non-contradicting extra detail -- and separates groundedness
# (does the answer contain unsupported/contradicting claims?) from the verdict
# so a genuinely complete-and-correct answer is never marked down for detail
# the gold happened not to capture. NEVER changes DEFAULT_JUDGE_PROMPT (judge/1
# stays the byte-identical default for every existing caller).
JUDGE_PROMPT_V2 = """You are an impartial scorer for a memory-benchmark question.

Question: {question}
Gold answer: {gold}
System answer: {pred}

Score the SYSTEM ANSWER against the GOLD ANSWER on two independent axes.

1) verdict -- does the system answer convey the gold answer?
   - "correct": the system answer states the same fact(s) as the gold answer.
     Aliases, abbreviations, and equal-or-greater specificity all count as a
     match (e.g. "LeBron" satisfies gold "LeBron James"; "the Lord of the
     Rings trilogy" satisfies gold "Lord of the Rings"). Extra correct detail
     that does NOT contradict the gold answer must NOT lower the verdict.
   - "partial": the right entity/fact is present but a required part of the
     gold answer is missing, or a minor part is wrong.
   - "incorrect": the system answer is wrong, contradicts the gold answer, or
     is empty.
   - "abstain": the system answer is exactly "unknown".

2) groundedness -- recorded separately, must NEVER change the verdict above:
   - "grounded": every claim in the system answer is supported by the gold
     answer or is a reasonable inference from it.
   - "unsupported_extra": the system answer adds extra claims not supported
     by the gold answer, but they do not contradict it.
   - "contradicts": the system answer contains a claim that contradicts the
     gold answer.
   - "na": not applicable (e.g. the verdict is "abstain").

Respond ONLY with strict JSON in this exact shape:
{{"verdict": "correct" | "partial" | "incorrect" | "abstain", "groundedness": "grounded" | "unsupported_extra" | "contradicts" | "na", "rationale": "one short sentence"}}"""

# Version registry: "judge/1" is the pre-existing DEFAULT_JUDGE_PROMPT, kept as
# the byte-identical default for every current caller. Bump when the contract
# changes; record the version alongside every verdict so runs stay comparable.
JUDGE_PROMPT_VERSIONS = {"judge/1": DEFAULT_JUDGE_PROMPT, "judge/2": JUDGE_PROMPT_V2}
DEFAULT_JUDGE_PROMPT_VERSION = "judge/1"

_GROUNDEDNESS_VALUES = {"grounded", "unsupported_extra", "contradicts", "na"}


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


def _parse_judge_json(
    text: str, *, judge_name: str, judge_model: str
) -> tuple[JudgeVerdict, str | None]:
    """Parse a judge JSON response into (verdict, groundedness). ``groundedness``
    is None for judge/1 responses (no such field) or an unrecognized value."""
    try:
        data = json.loads(_strip_json_fence(text))
    except json.JSONDecodeError as exc:
        raise ValueError("judge returned unparseable JSON") from exc
    verdict = data.get("verdict")
    score_map = {"correct": 1.0, "partial": 0.5, "incorrect": 0.0, "abstain": 0.0}
    if verdict not in score_map:
        raise ValueError("judge returned invalid verdict")
    rationale = str(data.get("rationale") or "judge returned no rationale")
    groundedness = data.get("groundedness")
    if groundedness not in _GROUNDEDNESS_VALUES:
        groundedness = None
    return JudgeVerdict(verdict, score_map[verdict], rationale, judge_name, judge_model), groundedness


def _verdict_from_json_text(text: str, *, judge_name: str, judge_model: str) -> JudgeVerdict:
    verdict, _ = _parse_judge_json(text, judge_name=judge_name, judge_model=judge_model)
    return verdict


class ClaudeJudge:
    name = "claude"

    def __init__(
        self,
        model: str | None = None,
        *,
        prompt_version: str = DEFAULT_JUDGE_PROMPT_VERSION,
    ):
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
        if prompt_version not in JUDGE_PROMPT_VERSIONS:
            raise ValueError(f"unknown judge prompt version: {prompt_version!r}")
        self.model = model
        self.prompt_version = prompt_version
        self._client = Anthropic(api_key=api_key)
        self.last_groundedness: str | None = None

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        # getattr preserves judge/1 behavior for established tests/callers that
        # construct ClaudeJudge via __new__ and inject a fake client.
        prompt_version = getattr(self, "prompt_version", DEFAULT_JUDGE_PROMPT_VERSION)
        prompt = JUDGE_PROMPT_VERSIONS[prompt_version].format(
            question=question, gold=gold, pred=pred
        )
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            raise RuntimeError(f"judge request failed: {type(exc).__name__}") from exc
        usage = getattr(response, "usage", None)
        self.last_usage = {
            "prompt_tokens": getattr(usage, "input_tokens", None),
            "completion_tokens": getattr(usage, "output_tokens", None),
        } if usage is not None else None
        verdict, groundedness = _parse_judge_json(
            response.content[0].text,
            judge_name=self.name,
            judge_model=self.model,
        )
        self.last_groundedness = groundedness
        return verdict

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
        prompt_version = getattr(self, "prompt_version", DEFAULT_JUDGE_PROMPT_VERSION)
        for item in items:
            if item.custom_id in seen_ids:
                raise ValueError(f"duplicate custom_id in batch: {item.custom_id!r}")
            seen_ids.add(item.custom_id)
            prompt = JUDGE_PROMPT_VERSIONS[prompt_version].format(
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

    def __init__(self, model: str | None = None, *, prompt_version: str = DEFAULT_JUDGE_PROMPT_VERSION):
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
        if prompt_version not in JUDGE_PROMPT_VERSIONS:
            raise ValueError(f"unknown judge prompt version: {prompt_version!r}")
        self.model = model
        self.prompt_version = prompt_version
        self._client = OpenAI(api_key=api_key)
        self.last_groundedness: str | None = None

    @staticmethod
    def _uses_completion_token_budget(model: str) -> bool:
        model_id = model.lower()
        return model_id.startswith(("gpt-5", "o1", "o3", "o4"))

    def score(self, *, question, gold, pred) -> JudgeVerdict:
        # getattr, not self.prompt_version: some tests construct this class via
        # object.__new__ to inject a fake client, bypassing __init__ entirely.
        prompt_version = getattr(self, "prompt_version", DEFAULT_JUDGE_PROMPT_VERSION)
        prompt = JUDGE_PROMPT_VERSIONS[prompt_version].format(question=question, gold=gold, pred=pred)
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
        usage = getattr(response, "usage", None)
        # Additive telemetry side-channel (JudgeVerdict is frozen and widely
        # used); the run recorder reads last_usage after each score() call.
        self.last_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
        } if usage is not None else None
        text = response.choices[0].message.content or ""
        verdict, groundedness = _parse_judge_json(text, judge_name=self.name, judge_model=self.model)
        self.last_groundedness = groundedness
        return verdict

    def _build_batch_request(self, item: JudgeBatchItem) -> dict:
        prompt_version = getattr(self, "prompt_version", DEFAULT_JUDGE_PROMPT_VERSION)
        prompt = JUDGE_PROMPT_VERSIONS[prompt_version].format(
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


def build_judge(
    name: str | None, model: str | None = None, *, prompt_version: str = DEFAULT_JUDGE_PROMPT_VERSION
) -> Judge | None:
    if name is None or name == "none":
        return None
    if name == "stub":
        return StubJudge()
    if name == "claude":
        return ClaudeJudge(model=model, prompt_version=prompt_version)
    if name == "openai":
        return OpenAIJudge(model=model, prompt_version=prompt_version)
    raise ValueError(f"unknown judge: {name!r} (use stub|claude|openai|none)")
