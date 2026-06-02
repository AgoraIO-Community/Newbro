import os
import pytest

from newbro.executors.node.workspace_files import (
    WorkspaceFileAccessError,
    iter_file_bytes,
    resolve_within_workspace,
)


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "ws"
    (root / "sub").mkdir(parents=True)
    (root / "report.pdf").write_bytes(b"hello")
    (root / "sub" / "out.csv").write_bytes(b"a,b")
    return root


def test_allows_file_in_workspace(workspace):
    real = resolve_within_workspace(str(workspace / "report.pdf"), str(workspace))
    assert real == (workspace / "report.pdf").resolve()


def test_allows_nested_file(workspace):
    real = resolve_within_workspace(str(workspace / "sub" / "out.csv"), str(workspace))
    assert real.name == "out.csv"


def test_denies_absolute_outside(workspace):
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace("/etc/hosts", str(workspace))
    assert exc.value.code == "denied"


def test_denies_parent_traversal(workspace):
    outside = workspace.parent / "secret.txt"
    outside.write_text("x")
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace(str(workspace / ".." / "secret.txt"), str(workspace))
    assert exc.value.code == "denied"


def test_denies_symlink_pointing_outside(workspace):
    target = workspace.parent / "outside.txt"
    target.write_text("secret")
    link = workspace / "link.txt"
    link.symlink_to(target)
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace(str(link), str(workspace))
    assert exc.value.code == "denied"


def test_denies_directory(workspace):
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace(str(workspace / "sub"), str(workspace))
    assert exc.value.code == "denied"


def test_not_found(workspace):
    with pytest.raises(WorkspaceFileAccessError) as exc:
        resolve_within_workspace(str(workspace / "missing.txt"), str(workspace))
    assert exc.value.code == "not_found"


def test_too_large(workspace):
    real = resolve_within_workspace(str(workspace / "report.pdf"), str(workspace))
    with pytest.raises(WorkspaceFileAccessError) as exc:
        list(iter_file_bytes(real, max_bytes=2))
    assert exc.value.code == "too_large"


def test_iter_file_bytes_yields_whole_file(workspace):
    real = resolve_within_workspace(str(workspace / "report.pdf"), str(workspace))
    assert b"".join(iter_file_bytes(real, chunk_bytes=2)) == b"hello"
