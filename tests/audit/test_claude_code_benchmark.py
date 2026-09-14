"""Subscription transport exercised through benchmark interfaces and a fake executable."""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

MODEL = "claude-haiku-4-5-20251001"
FAKE_CLI = '''#!PYTHON
import json, os, sys, pathlib, time
root = pathlib.Path(__file__).parent
config = json.loads((root / "config.json").read_text())
assert not any(k.startswith(("ANTHROPIC_", "CLAUDE_", "AWS_", "GOOGLE_", "AZURE_")) for k in os.environ)
assert pathlib.Path.cwd() != root and not (pathlib.Path.cwd() / "AGENTS.md").exists()
args = sys.argv[1:]
assert "--safe-mode" in args and "--setting-sources" in args
if "auth" in args:
    print(json.dumps(config.get("auth", {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "firstParty"})))
    sys.exit(0)
assert "--bare" not in args and "--fallback-model" not in args
for flag in ("--strict-mcp-config", "--no-session-persistence", "--print"):
    assert flag in args
assert args[args.index("--tools") + 1] == ""
assert args[args.index("--model") + 1] == "claude-haiku-4-5-20251001"
assert args[args.index("--output-format") + 1] == "json"
assert args[args.index("--system-prompt") + 1]
assert float(args[args.index("--max-budget-usd") + 1]) > 0
prompt = sys.stdin.read()
assert "Question:" in prompt
with (root / "calls").open("a") as f: f.write("call\\n")
if config.get("sleep"): time.sleep(config["sleep"])
if config.get("stderr"): print(config["stderr"], file=sys.stderr)
if "raw" in config: print(config["raw"])
else:
    response = config["response"]
    if config.get("judge") and "Gold answer:" in prompt:
        response["result"] = '{"verdict":"correct","rationale":"Matches."}'
    print(json.dumps(response))
sys.exit(config.get("exit", 0))
'''


@pytest.fixture
def cli(tmp_path):
    executable = tmp_path / "claude"
    executable.write_text(FAKE_CLI.replace("#!PYTHON", "#!" + sys.executable))
    executable.chmod(0o755)
    response = {
        "type": "result", "subtype": "success", "is_error": False, "result": "Alice",
        "total_cost_usd": 0.002,
        "usage": {"input_tokens": 12, "output_tokens": 3, "cache_read_input_tokens": 4, "cache_creation_input_tokens": 5},
        "modelUsage": {MODEL: {"inputTokens": 15, "outputTokens": 4, "cacheReadInputTokens": 4, "cacheCreationInputTokens": 5, "costUSD": 0.002}},
        "session_id": "PRIVATE-SENTINEL",
    }
    config = {"response": response}
    def run(source, **settings):
        (tmp_path / "config.json").write_text(json.dumps(config))
        env = dict(os.environ, PATH=str(tmp_path), ANTHROPIC_API_KEY="PRIVATE-SENTINEL", CLAUDE_CODE_OAUTH_TOKEN="PRIVATE-SENTINEL", CLAUDE_CODE_USE_BEDROCK="1", AWS_PROFILE="PRIVATE-SENTINEL")
        env.update(settings)
        result = subprocess.run([sys.executable, "-c", source], env=env, text=True, capture_output=True, timeout=30)
        return result
    return config, run, tmp_path


ANSWER = '''from benchmarks.external.common.answerer import generate_short_answer
import json
diag = {}
answer = generate_short_answer("claude-code", None, "Who paid?", "Alice paid.", diag_out=diag)
print(json.dumps({"answer": answer, "diag": diag}))
'''


def test_subscription_answer_and_diagnostics_are_isolated(cli):
    _, run, _ = cli
    result = run(ANSWER)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["answer"] == "Alice"
    assert data["diag"]["served_model"] == MODEL
    assert data["diag"]["prompt_tokens"] == 12
    assert data["diag"]["cache_read_input_tokens"] == 4
    assert data["diag"]["cli_reported_cost_usd"] == 0.002
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr


@pytest.mark.parametrize("field,value", [
    ("total_cost_usd", None), ("total_cost_usd", -1), ("total_cost_usd", float("nan")),
    ("usage", {}), ("usage", {"input_tokens": -1, "output_tokens": 3}),
    ("modelUsage", {}), ("modelUsage", {"sonnet": {}}),
])
def test_answer_fails_closed_on_missing_or_invalid_accounting(cli, field, value):
    config, run, _ = cli
    config["response"][field] = value
    result = run(ANSWER)
    assert result.returncode != 0
    assert "claude-code:" in result.stderr
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr


@pytest.mark.parametrize("settings", [
    {"SEAM_BENCH_CLAUDE_CODE_TOTAL_BUDGET_USD": "0.10"},
    {"SEAM_BENCH_CLAUDE_CODE_MAX_CALLS": "1"},
])
def test_parallel_answer_calls_share_process_allowance(cli, settings):
    _, run, root = cli
    result = run('''from concurrent.futures import ThreadPoolExecutor
from benchmarks.external.common.answerer import generate_short_answer
def call(_):
    try:
        return generate_short_answer("claude-code", None, "Who paid?", "Alice paid.")
    except RuntimeError:
        return "blocked"
with ThreadPoolExecutor(max_workers=4) as pool:
    answers = list(pool.map(call, range(4)))
assert answers.count("Alice") == 1, answers
assert answers.count("blocked") == 3, answers
''', **settings)
    assert result.returncode == 0, result.stderr
    assert (root / "calls").read_text().splitlines() == ["call"]


def test_timed_out_retry_consumes_allowance(cli):
    config, run, root = cli
    config["sleep"] = 2
    result = run('''from benchmarks.external.common.answerer import generate_short_answer
from benchmarks.external.common.provider_retry import provider_retry
try:
    provider_retry(lambda: generate_short_answer("claude-code", None, "Who paid?", "Alice"), label="test", max_attempts=3, base_delay=0)
except RuntimeError as exc:
    assert "allowance exhausted" in str(exc), str(exc)
else:
    raise AssertionError("expected failure")
''', SEAM_BENCH_CLAUDE_CODE_TIMEOUT_SECONDS="0.3", SEAM_BENCH_CLAUDE_CODE_MAX_CALLS="1")
    assert result.returncode == 0, result.stderr
    assert (root / "calls").read_text().splitlines() == ["call"]


def test_subscription_judge_scores_and_shares_answerer_allowance(cli):
    config, run, root = cli
    config["response"]["result"] = '{"verdict":"correct","rationale":"Same payer.","groundedness":"grounded"}'
    result = run('''from benchmarks.external.common.judge import build_judge
from benchmarks.external.common.answerer import generate_short_answer
judge = build_judge("claude-code", prompt_version="judge/2")
verdict = judge.score(question="Who paid?", gold="Alice", pred="Alice")
assert verdict.score == 1.0
assert verdict.judge_name == "claude-code"
assert judge.last_groundedness == "grounded"
assert judge.last_usage["cli_reported_cost_usd"] == 0.002
try:
    generate_short_answer("claude-code", None, "Who paid?", "Alice")
except RuntimeError as exc:
    assert "allowance exhausted" in str(exc)
else:
    raise AssertionError("judge and answerer must share budget")
''', SEAM_BENCH_CLAUDE_CODE_MAX_CALLS="1")
    assert result.returncode == 0, result.stderr
    assert (root / "calls").read_text().splitlines() == ["call"]


@pytest.mark.parametrize("flag", ["--answerer", "--judge", "--judge-cross"])
def test_runner_subscription_requires_paid_opt_in(cli, flag):
    _, run, root = cli
    result = run(f'''import sys
from benchmarks.external.locomo.run import main
sys.argv = ["locomo", "--quickstart", {flag!r}, "claude-code"]
main()
''')
    assert result.returncode == 2
    assert "requires --allow-paid" in result.stderr
    assert not (root / "calls").exists()


def test_runner_rejects_subscription_batch_before_spending(cli):
    _, run, root = cli
    result = run('''import sys
from benchmarks.external.locomo.run import main
sys.argv = ["locomo", "--quickstart", "--answerer", "claude-code", "--judge", "claude-code", "--judge-batch", "--allow-paid"]
main()
''')
    assert result.returncode == 2
    assert "claude-code does not support --judge-batch" in result.stderr
    assert not (root / "calls").exists()


# Fake only the external embedding libraries; run real SEAM retrieval/SQLite.
FAKE_EMBEDDER = '''import sys, types
import huggingface_hub
huggingface_hub.snapshot_download = lambda **kwargs: "/fake/offline/model"
class Vector:
    def tolist(self): return [1.0] + [0.0] * 383
class SentenceTransformer:
    def __init__(self, *args, **kwargs): pass
    def get_sentence_embedding_dimension(self): return 384
    def encode(self, *args, **kwargs): return Vector()
sys.modules["sentence_transformers"] = types.SimpleNamespace(SentenceTransformer=SentenceTransformer)
'''


def test_seam_answer_uses_subscription_transport(cli):
    _, run, _ = cli
    result = run(FAKE_EMBEDDER + '''from benchmarks.external.locomo.adapters.seam import SeamLocomoAdapter
adapter = SeamLocomoAdapter(answerer="claude-code")
try:
    adapter.reset("test")
    from benchmarks.external.common.types import ConversationTurn
    adapter.ingest_turn("test", ConversationTurn("Alice", "Alice paid the restaurant bill."))
    answer = adapter.answer("test", "Who paid?")
    assert answer.generated_answer == "Alice", answer
    assert answer.answerer_diagnostics["cli_reported_cost_usd"] == 0.002
finally:
    adapter.close()
''')
    assert result.returncode == 0, result.stderr


def runner_source(root, flags):
    return FAKE_EMBEDDER + f'''from benchmarks.external.locomo.run import main
sys.argv = ["locomo", "--quickstart", "--limit", "1", "--allow-paid", "--output", {str(root / "report.json")!r}] + {flags!r}
main()
'''


def test_runner_preserves_subscription_accounting_without_context_flag(cli):
    config, run, root = cli
    config["judge"] = True
    result = run(runner_source(root, ["--answerer", "claude-code", "--judge", "claude-code", "--judge-cross", "claude-code"]), SEAM_BENCH_RESULTS_DIR=str(root / "archive"))
    assert result.returncode == 0, result.stderr
    report = json.loads((root / "report.json").read_text())
    case = report["cases"][0]
    assert case["answerer_diagnostics"]["cli_reported_cost_usd"] == 0.002
    assert case["judge"]["usage"]["model_usage"][MODEL]["inputTokens"] == 15
    assert case["judge_cross"]["usage"]["billing_basis"] == "claude-code-reported-usd-not-account-charge"
    assert "PRIVATE-SENTINEL" not in json.dumps(report)


def test_runner_subscription_judge_failure_is_nonzero_with_preserved_report(cli):
    config, run, root = cli
    config["response"]["is_error"] = True
    result = run(runner_source(root, ["--judge", "claude-code"]), SEAM_BENCH_RESULTS_DIR=str(root / "archive"))
    assert result.returncode != 0
    assert "claude-code" in result.stderr
    report = json.loads((root / "report.json").read_text())
    assert "error" in report["cases"][0]["judge"]
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr + json.dumps(report)


def test_run_record_preserves_reported_cost_separately_from_estimate(cli):
    _, run, _ = cli
    result = run(ANSWER + '''from benchmarks.external.common.run_record import RunRecord
record = RunRecord()
record.add_case(case_id="one", scope="test", category="1", arm="seam", question="Who paid?", gold_answer="Alice", raw_answer=answer, verdict="correct", judge_score=1, judge_rationale="Matches.", judge_model="claude-haiku-4-5-20251001", retrieved_context="Alice paid.", context_recall=1, answerer_diagnostics=diag, judge_usage=diag)
for role in ("answerer", "judge"):
    usage = record.cases[0][role]
    assert usage["cli_reported_cost_usd"] == 0.002
    assert usage["billing_basis"] == "claude-code-reported-usd-not-account-charge"
    assert usage["model_usage"]["claude-haiku-4-5-20251001"]["inputTokens"] == 15
    assert "cost_usd" in usage
''')
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("patch", [
    {"raw": "PRIVATE-SENTINEL invalid JSON"}, {"raw": "[]"},
    {"exit": 1, "stderr": "PRIVATE-SENTINEL"},
    {"auth": {"loggedIn": False, "authMethod": "claude.ai", "apiProvider": "firstParty"}},
    {"auth": {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"}},
    {"auth": {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"}},
])
def test_cli_and_auth_failures_never_expose_content_or_fall_back(cli, patch):
    config, run, root = cli
    config.update(patch)
    result = run(ANSWER)
    assert result.returncode != 0
    assert "claude-code:" in result.stderr
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr
    if "auth" in patch:
        assert not (root / "calls").exists()


@pytest.mark.parametrize("field,value", [
    ("result", "   "), ("result", None), ("is_error", True),
    ("subtype", "error_max_budget_usd"), ("total_cost_usd", True),
    ("usage", {"input_tokens": True}), ("modelUsage", {"claude-other-model": {}}),
])
def test_result_errors_fail_closed(cli, field, value):
    config, run, _ = cli
    config["response"][field] = value
    result = run(ANSWER)
    assert result.returncode != 0
    assert "claude-code:" in result.stderr
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr


@pytest.mark.parametrize("settings", [
    {"PATH": ""}, {"SEAM_BENCH_CLAUDE_CODE_MAX_BUDGET_USD": "0"},
    {"SEAM_BENCH_CLAUDE_CODE_TOTAL_BUDGET_USD": "nan"},
    {"SEAM_BENCH_CLAUDE_CODE_MAX_CALLS": "0"},
    {"SEAM_BENCH_CLAUDE_CODE_TIMEOUT_SECONDS": "inf"},
    {"SEAM_BENCH_CLAUDE_CODE_TOTAL_BUDGET_USD": "0.01"},
])
def test_unavailable_cli_and_invalid_limits_prevent_spending(cli, settings):
    _, run, root = cli
    result = run(ANSWER, **settings)
    assert result.returncode != 0
    assert "claude-code:" in result.stderr
    assert not (root / "calls").exists()


def test_model_alias_rejected_without_provider_launch(cli):
    _, run, root = cli
    result = run(ANSWER.replace('"claude-code", None', '"claude-code", "haiku"'))
    assert result.returncode != 0
    assert "explicit full model required" in result.stderr
    assert not (root / "calls").exists()


def test_optional_cli_model_metadata_is_preserved_without_raw_fields(cli):
    config, run, _ = cli
    config["response"]["modelUsage"][MODEL].update({
        "provider": "firstParty", "costBasis": "list", "canonicalModel": "claude-haiku-4-5",
        "thinkingTokens": 2, "privateExtra": "PRIVATE-SENTINEL",
    })
    result = run(ANSWER)
    assert result.returncode == 0, result.stderr
    usage = json.loads(result.stdout)["diag"]["model_usage"][MODEL]
    assert usage["canonicalModel"] == "claude-haiku-4-5"
    assert usage["costBasis"] == "list"
    assert usage["provider"] == "firstParty"
    assert usage["thinkingTokens"] == 2
    assert "PRIVATE-SENTINEL" not in result.stdout


def test_oversize_cli_output_fails_closed(cli):
    config, run, _ = cli
    config["response"]["result"] = "x" * (1024 * 1024)
    result = run(ANSWER)
    assert result.returncode != 0
    assert "CLI output too large" in result.stderr
    assert len(result.stderr) < 5000


@pytest.mark.parametrize("flag,report_key", [("--judge", "judge"), ("--judge-cross", "judge_cross")])
def test_runner_preserves_known_usage_when_judge_verdict_is_invalid(cli, flag, report_key):
    config, run, root = cli
    config["response"]["result"] = '{"verdict":"not-a-verdict","rationale":"PRIVATE-SENTINEL"}'
    result = run(runner_source(root, [flag, "claude-code"]), SEAM_BENCH_RESULTS_DIR=str(root / "archive"))
    assert result.returncode != 0
    report = json.loads((root / "report.json").read_text())
    judged = report["cases"][0][report_key]
    assert judged["error"] == "claude-code: invalid judge verdict"
    assert judged["usage"]["cli_reported_cost_usd"] == 0.002
    assert judged["usage"]["model_usage"][MODEL]["inputTokens"] == 15
    assert judged["usage"]["billing_basis"] == "claude-code-reported-usd-not-account-charge"
    assert (root / "calls").read_text().splitlines() == ["call"]
    assert "PRIVATE-SENTINEL" not in result.stdout + result.stderr + json.dumps(report)
