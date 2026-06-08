from council.routing import classify_path, split_diff_by_type


def test_classify_by_extension():
    assert classify_path("README.md") == "doc"
    assert classify_path("notes/today.rst") == "doc"
    assert classify_path("a/b/thing.txt") == "doc"
    assert classify_path("design.adoc") == "doc"
    assert classify_path("src/app.py") == "code"
    assert classify_path("lib/util.js") == "code"


def test_classify_by_directory_segment():
    assert classify_path("docs/architecture.png") == "doc"   # under docs/
    assert classify_path("specs/api/example.py") == "doc"     # under specs/
    assert classify_path("plans/q3.json") == "doc"
    assert classify_path("plan/rollout.yaml") == "doc"
    assert classify_path("src/docs_helper.py") == "code"      # 'docs' only as a substring, not a segment


def test_classify_empty_is_code():
    assert classify_path("") == "code"
    assert classify_path("   ") == "code"


CODE_FILE = (
    "diff --git a/src/app.py b/src/app.py\n"
    "index 111..222 100644\n--- a/src/app.py\n+++ b/src/app.py\n"
    "@@ -1 +1 @@\n-old\n+new\n"
)
DOC_FILE = (
    "diff --git a/docs/design.md b/docs/design.md\n"
    "index 333..444 100644\n--- a/docs/design.md\n+++ b/docs/design.md\n"
    "@@ -1 +1 @@\n-old doc\n+new doc\n"
)


def test_split_mixed_diff():
    code_diff, doc_diff = split_diff_by_type(CODE_FILE + DOC_FILE)
    assert "src/app.py" in code_diff and "docs/design.md" not in code_diff
    assert "docs/design.md" in doc_diff and "src/app.py" not in doc_diff


def test_split_code_only():
    code_diff, doc_diff = split_diff_by_type(CODE_FILE)
    assert "src/app.py" in code_diff
    assert doc_diff == ""


def test_split_doc_only():
    code_diff, doc_diff = split_diff_by_type(DOC_FILE)
    assert code_diff == ""
    assert "docs/design.md" in doc_diff


def test_split_empty_or_garbage():
    assert split_diff_by_type("") == ("", "")
    assert split_diff_by_type("not a diff at all") == ("", "")
