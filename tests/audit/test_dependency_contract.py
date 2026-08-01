from pathlib import Path

from tools.ci.verify_dependency_contract import verify


def test_repository_dependency_contract_is_coherent():
    repo = Path(__file__).resolve().parents[2]
    assert verify(repo) == []
