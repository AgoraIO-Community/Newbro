from newbro.protocol import (
    ReadWorkspaceFileCommand,
    WorkspaceFileChunk,
    WorkspaceFileEof,
    WorkspaceFileError,
)


def test_read_command_round_trip():
    cmd = ReadWorkspaceFileCommand(request_id="r1", thread_id="t1", path="/work/a.txt")
    assert cmd.type == "read_workspace_file"
    assert ReadWorkspaceFileCommand.model_validate(cmd.model_dump(mode="json")) == cmd


def test_chunk_eof_error_round_trip():
    chunk = WorkspaceFileChunk(request_id="r1", seq=0, data="QUJD")
    eof = WorkspaceFileEof(request_id="r1", total_bytes=3, sha256="abc")
    err = WorkspaceFileError(request_id="r1", code="denied", message="nope")
    assert chunk.type == "workspace_file_chunk"
    assert eof.type == "workspace_file_eof"
    assert err.type == "workspace_file_error"
    assert WorkspaceFileChunk.model_validate(chunk.model_dump(mode="json")) == chunk
    assert WorkspaceFileEof.model_validate(eof.model_dump(mode="json")) == eof
    assert WorkspaceFileError.model_validate(err.model_dump(mode="json")) == err


def test_error_code_is_constrained():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        WorkspaceFileError(request_id="r1", code="bogus", message="x")
