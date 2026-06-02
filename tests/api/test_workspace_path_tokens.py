from newbro.api.workspace_path_tokens import extract_path_tokens


def test_extracts_absolute_path_with_trailing_sentence_punctuation():
    assert extract_path_tokens("saved to /work/out/report.pdf.") == {"/work/out/report.pdf"}


def test_strips_backticks_and_quotes_and_parens():
    assert extract_path_tokens("see `/work/a.txt`") == {"/work/a.txt"}
    assert extract_path_tokens('see "/work/a.txt"') == {"/work/a.txt"}
    assert extract_path_tokens("(see /work/a.txt)") == {"/work/a.txt"}


def test_ignores_relative_paths_and_prose():
    assert extract_path_tokens("out/report.pdf and hello world") == set()


def test_dedupes_and_keeps_distinct_tokens():
    assert extract_path_tokens("/a /a /b") == {"/a", "/b"}


def test_passwd_and_passwd_txt_are_distinct_tokens():
    tokens = extract_path_tokens("/etc/passwd.txt")
    assert "/etc/passwd" not in tokens
    assert tokens == {"/etc/passwd.txt"}


def test_handles_none_and_empty():
    assert extract_path_tokens(None) == set()
    assert extract_path_tokens("") == set()
