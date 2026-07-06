"""W1 — /tree endpoint safety: path traversal + DoS hardening."""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from seam_runtime.runtime import SeamRuntime
from seam_runtime.server import create_app


@pytest.fixture
def tree_client(tmp_path):
    """Create a TestClient with SEAM_API_TREE_ROOT pointed at tmp_path."""
    os.environ["SEAM_API_TREE_ROOT"] = str(tmp_path)
    runtime = SeamRuntime(":memory:")
    app = create_app(runtime)
    yield TestClient(app)
    os.environ.pop("SEAM_API_TREE_ROOT", None)


def _make_tree(root: Path) -> None:
    """Populate root with a small file tree for tree-walking tests."""
    (root / "readme.md").write_text("hello")
    sub = root / "subdir"
    sub.mkdir()
    (sub / "notes.txt").write_text("world")
    deeper = sub / "deeper"
    deeper.mkdir()
    (deeper / "data.json").write_text("{}")


def test_tree_rejects_path_outside_root(tree_client, tmp_path):
    """GET /tree?path=/etc returns 400 with detail mentioning 'outside root'."""
    resp = tree_client.get("/tree", params={"path": "/etc"})
    assert resp.status_code == 400
    assert "outside root" in resp.json()["detail"].lower()


def test_tree_rejects_dotdot_traversal(tree_client, tmp_path):
    """GET /tree?path=../.. returns 400 with detail mentioning 'outside root'."""
    resp = tree_client.get("/tree", params={"path": "../.."})
    assert resp.status_code == 400
    assert "outside root" in resp.json()["detail"].lower()


def test_tree_404_for_missing_path(tree_client, tmp_path):
    """GET /tree?path=does-not-exist returns 404."""
    resp = tree_client.get("/tree", params={"path": "does-not-exist"})
    assert resp.status_code == 404


def test_tree_returns_valid_shape(tree_client, tmp_path):
    """GET /tree?path=. returns 200 with correct response keys and relative ids."""
    _make_tree(tmp_path)
    resp = tree_client.get("/tree", params={"path": "."})
    assert resp.status_code == 200
    body = resp.json()
    for key in ("root", "path", "tree", "truncated", "entries_seen", "max_depth", "max_entries"):
        assert key in body, f"missing key: {key}"
    assert body["path"] == "."

    def check_ids(nodes):
        for node in nodes:
            assert not node["id"].startswith("/"), f"id must be relative: {node['id']}"
            if "children" in node:
                check_ids(node["children"])

    check_ids(body["tree"])


def test_tree_respects_max_depth(tree_client, tmp_path):
    """With SEAM_API_TREE_MAX_DEPTH=1, grandchild entries never appear."""
    _make_tree(tmp_path)
    os.environ["SEAM_API_TREE_MAX_DEPTH"] = "1"
    try:
        resp = tree_client.get("/tree", params={"path": "."})
        assert resp.status_code == 200
        body = resp.json()
        assert body["max_depth"] == 1

        def check_depth(nodes, current_depth):
            for node in nodes:
                if "children" in node:
                    if current_depth >= 1:
                        assert node["children"] == [], (
                            f"grandchild at depth {current_depth} should have empty children"
                        )
                    else:
                        check_depth(node["children"], current_depth + 1)

        check_depth(body["tree"], 0)
    finally:
        os.environ.pop("SEAM_API_TREE_MAX_DEPTH", None)


def test_tree_respects_max_entries(tree_client, tmp_path):
    """With SEAM_API_TREE_MAX_ENTRIES=2, truncated == True."""
    # Create enough entries to exceed the cap
    for i in range(10):
        (tmp_path / f"file_{i}.txt").write_text("x")
    os.environ["SEAM_API_TREE_MAX_ENTRIES"] = "2"
    try:
        resp = tree_client.get("/tree", params={"path": "."})
        assert resp.status_code == 200
        body = resp.json()
        assert body["truncated"] is True
        assert body["entries_seen"] >= 2
    finally:
        os.environ.pop("SEAM_API_TREE_MAX_ENTRIES", None)


@pytest.mark.skipif(sys.platform != "linux", reason="chmod 000 requires Linux")
def test_tree_unreadable_subdir_graceful(tree_client, tmp_path):
    """GET /tree on tree with unreadable dir reports error key, no raise."""
    _make_tree(tmp_path)
    locked = tmp_path / "locked_dir"
    locked.mkdir()
    (locked / "secret.txt").write_text("hidden")
    os.chmod(locked, 0o000)
    try:
        resp = tree_client.get("/tree", params={"path": "."})
        assert resp.status_code == 200
        body = resp.json()
        # Walk the tree looking for the locked_dir node
        def find_locked(nodes):
            for node in nodes:
                if node.get("name") == "locked_dir":
                    return node
                if "children" in node:
                    found = find_locked(node["children"])
                    if found:
                        return found
            return None

        locked_node = find_locked(body["tree"])
        assert locked_node is not None, "locked_dir must appear in tree"
        assert locked_node.get("type") == "folder"
        # Accept either empty children or an error key
        if locked_node.get("children") == [] or locked_node.get("error"):
            pass
        else:
            pytest.fail(f"locked_dir node should have empty children or error key: {locked_node}")
    finally:
        os.chmod(locked, 0o755)


def test_tree_rejects_non_directory(tree_client, tmp_path):
    """GET /tree?path=readme.md (a file) returns 400 'not a directory'."""
    (tmp_path / "readme.md").write_text("hello")
    resp = tree_client.get("/tree", params={"path": "readme.md"})
    assert resp.status_code == 400
    assert "not a directory" in resp.json()["detail"].lower()
