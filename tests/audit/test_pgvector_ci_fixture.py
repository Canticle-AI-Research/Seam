"""The CI database must be owned, ephemeral and ready before any real test."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MODULE = "tools.ci.pgvector_fixture"

FAKE_DOCKER = r'''#!/usr/bin/env python3
import json, os, sys, time
from pathlib import Path
root = Path(os.environ['SEAM_FAKE_DOCKER_ROOT'])
args = sys.argv[1:]
selectors = ['DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_TLS', 'DOCKER_TLS_VERIFY', 'DOCKER_CERT_PATH']
entry = {'args': args, 'selectors_present': any(k in os.environ for k in selectors),
         'config_preserved': os.environ.get('DOCKER_CONFIG') == 'fixture-config-selector'}
password = os.environ.get('POSTGRES_PASSWORD')
entry['password_in_argv'] = bool(password and any(password in a for a in args))
with (root / 'calls.jsonl').open('a') as stream: stream.write(json.dumps(entry) + '\n')
if args.pop(0) != '--host=unix:///var/run/docker.sock' or entry['selectors_present']:
    raise SystemExit(77)
mode = os.environ.get('SEAM_FAKE_DOCKER_MODE', 'ready')
resource = root / 'container.json'
if args[0] == 'version':
    if mode == 'daemon_unavailable': raise SystemExit(1)
    print('1.51')
elif args[:2] == ['image', 'inspect']:
    print(json.dumps({'id': 'sha256:'+'b'*64, 'digests': ['pgvector/pgvector@sha256:'+'c'*64],
                      'volumes': {'/var/lib/postgresql': {}}, 'env': ['PGDATA=/var/lib/postgresql/18/docker']}))
elif args[0] == 'pull':
    pass
elif args[0] == 'create':
    labels = {}
    for i,a in enumerate(args):
        if a == '--label':
            k,v = args[i+1].split('=', 1); labels[k] = v
    name = args[args.index('--name')+1]
    data = {'id':'a'*64,'name':'/'+name,'labels':labels,'image_id':'sha256:'+'b'*64,
            'mounts':[{'Type':'tmpfs','Destination':'/var/lib/postgresql'}],
            'ports':{'5432/tcp':[{'HostIp':'127.0.0.1','HostPort':'55481'}]},
            'status':'running','health':'healthy'}
    if mode == 'timeout': data['health'] = 'starting'
    if mode == 'volume': data['mounts'] = [{'Type':'volume','Destination':'/var/lib/postgresql'}]
    resource.write_text(json.dumps(data))
    print('a'*64)
elif args[0] == 'inspect':
    if not resource.exists():
        print('Error: No such object', file=sys.stderr); raise SystemExit(1)
    if mode == 'late_healthy': time.sleep(0.05)
    print(resource.read_text())
elif args[0] == 'start':
    print('a'*64)
elif args[0] == 'exec':
    print('CREATE EXTENSION\n0.8.7\n18.3')
elif args[0] == 'rm':
    resource.unlink(missing_ok=True)
elif args[0] == 'ps':
    if '--filter' not in args or not args[args.index('--filter')+1].startswith('label=io.canticle.seam.pgvector-owner='):
        raise SystemExit(79)
    if resource.exists(): print('a'*64)
else:
    raise SystemExit('unrecognized fixture Docker operation')
'''


@pytest.fixture
def fake_docker(tmp_path):
    binary = tmp_path / "docker"
    binary.write_text(FAKE_DOCKER)
    binary.chmod(0o700)
    return tmp_path


def run_cli(root, action, *extra, mode="ready"):
    env = os.environ.copy()
    env.update({
        "PATH": str(root) + os.pathsep + env.get("PATH", ""),
        "SEAM_FAKE_DOCKER_ROOT": str(root), "SEAM_FAKE_DOCKER_MODE": mode,
        "DOCKER_HOST": "unix:///missing-desktop.sock", "DOCKER_CONTEXT": "stale-desktop",
        "DOCKER_TLS": "1", "DOCKER_TLS_VERIFY": "1", "DOCKER_CERT_PATH": "unused-selector",
        "DOCKER_CONFIG": "fixture-config-selector", "GITHUB_ACTIONS": "false", "SEAM_STRICT_NO_SKIP": "0",
    })
    return subprocess.run(
        [sys.executable, "-m", MODULE, action, "--state", str(root / "private/state.json"), *extra],
        cwd=ROOT, env=env, capture_output=True, text=True, check=False,
    )


def calls(root):
    path = root / "calls.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_public_lifecycle_clears_stale_endpoint_preserves_config_and_cleans_owned_fixture(fake_docker):
    result = run_cli(fake_docker, "start")
    assert result.returncode == 0, result.stderr
    state = fake_docker / "private/state.json"
    assert state.stat().st_mode & 0o777 == 0o600
    assert state.parent.stat().st_mode & 0o777 == 0o700
    trace = calls(fake_docker)
    assert all(not row["selectors_present"] and row["config_preserved"] for row in trace)
    create = next(row for row in trace if row["args"][1] == "create")
    assert not create["password_in_argv"]
    assert "127.0.0.1::5432" in create["args"]
    assert "type=tmpfs,destination=/var/lib/postgresql,tmpfs-size=536870912" in create["args"]
    result = run_cli(fake_docker, "stop")
    assert result.returncode == 0, result.stderr
    assert not state.exists() and not (fake_docker / "container.json").exists()
    removal = next(row for row in calls(fake_docker) if row["args"][1] == "rm")
    assert removal["args"][2:] == ["--force", "--volumes", "a" * 64]


def test_daemon_unavailable_fails_before_any_container_creation(fake_docker):
    result = run_cli(fake_docker, "start", mode="daemon_unavailable")
    assert result.returncode == 1
    assert "daemon unavailable" in result.stderr
    assert not any(row["args"][1] == "create" for row in calls(fake_docker))


@pytest.mark.parametrize("mode", ["timeout", "volume", "late_healthy"])
def test_failed_readiness_or_wrong_mount_cleans_own_partial_start(fake_docker, mode):
    result = run_cli(fake_docker, "start", "--timeout-seconds", "1" if mode == "volume" else "0.01", mode=mode)
    assert result.returncode == 1
    assert ("unexpected fixture mount" if mode == "volume" else "readiness timed out") in result.stderr
    assert not (fake_docker / "container.json").exists()
    assert not (fake_docker / "private/state.json").exists()


def test_cleanup_refuses_replaced_ownership_identity(fake_docker):
    assert run_cli(fake_docker, "start").returncode == 0
    path = fake_docker / "container.json"
    record = json.loads(path.read_text())
    record["labels"] = {"another-owner": "true"}
    path.write_text(json.dumps(record))
    result = run_cli(fake_docker, "stop")
    assert result.returncode == 1
    assert "ownership" in result.stderr
    assert path.exists()
    assert not any(row["args"][1] == "rm" for row in calls(fake_docker))


def test_cleanup_missing_never_started_state_is_safe_without_daemon(fake_docker):
    result = run_cli(fake_docker, "stop", mode="daemon_unavailable")
    assert result.returncode == 0
    assert calls(fake_docker) == []


def test_child_gets_only_owned_database_and_secret_output_is_redacted(fake_docker):
    assert run_cli(fake_docker, "start").returncode == 0
    result = run_cli(fake_docker, "run", "--", sys.executable, "-c", (
        "import os; print(os.environ['PGVECTOR_TEST_DSN']); "
        "print(os.environ['PGPASSWORD']); "
        "assert os.environ['PGVECTOR_TEST_DSN'] == os.environ['SEAM_PGVECTOR_DSN']; "
        "assert os.environ['SEAM_STRICT_NO_SKIP'] == '1'"
    ))
    assert result.returncode == 0, result.stderr
    assert "host=127.0.0.1 port=55481" in result.stdout
    assert "<redacted>" in result.stdout
    password = json.loads((fake_docker / "private/state.json").read_text())["password"]
    assert password not in result.stdout and password not in result.stderr
    assert run_cli(fake_docker, "stop").returncode == 0


def test_existing_state_cannot_be_overwritten_by_a_second_start(fake_docker):
    assert run_cli(fake_docker, "start").returncode == 0
    before = (fake_docker / "private/state.json").read_bytes()
    result = run_cli(fake_docker, "start")
    assert result.returncode == 1
    assert (fake_docker / "private/state.json").read_bytes() == before
    assert sum(row["args"][1] == "create" for row in calls(fake_docker)) == 1
    assert run_cli(fake_docker, "stop").returncode == 0


def test_ci_starts_after_guard_not_pre_step_services_and_always_cleans_up():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    job = workflow["jobs"]["pgvector-integration"]
    assert "services" not in job, "automatic service creation bypasses the approved daemon probe"
    steps = job["steps"]
    start = next(i for i,s in enumerate(steps) if "tools.ci.pgvector_fixture start" in s.get("run", ""))
    run = next(i for i,s in enumerate(steps) if "tools.ci.pgvector_fixture run" in s.get("run", ""))
    stop = next(s for s in steps if "tools.ci.pgvector_fixture stop" in s.get("run", ""))
    assert start < run
    assert stop.get("if") == "always()"
    assert "PGVECTOR_TEST_DSN" not in json.dumps(job), "owned DSNs belong only in the fixture test child"
    compose = yaml.safe_load((ROOT / "docker-compose.yaml").read_text())
    from tools.ci.pgvector_fixture import IMAGE
    assert compose["services"]["pgvector"]["image"] == IMAGE == "pgvector/pgvector:0.8.7-pg18-trixie"
