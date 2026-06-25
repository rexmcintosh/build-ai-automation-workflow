import importlib.util, pathlib

_spec = importlib.util.spec_from_file_location(
    "venice_review", pathlib.Path("setup/templates/venice_review.py"))
vr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(vr)


def test_shim_exposes_main_and_post_comment():
    assert hasattr(vr, "main") and callable(vr.main)
    assert hasattr(vr, "post_comment") and callable(vr.post_comment)


def test_shim_delegates_to_run_pr_review():
    # the orchestration logic must live in the package, not the script
    import inspect
    src = inspect.getsource(vr)
    assert "from council.review import run_pr_review" in src
    assert "run_pr_review(" in src
    assert "build_review" not in src  # old per-script logic is gone


def test_shim_wires_grounding_and_determinism():
    # S1 (file context), E3 (temperature=0), S2 (in-place comment marker)
    import inspect
    src = inspect.getsource(vr)
    assert "file_context=" in src                 # full-file context reaches the engine (S1)
    assert "temperature=0" in src                 # deterministic gate path (E3)
    assert vr.MARKER in src                        # rolling single comment (S2)


def test_gather_file_context_reads_changed_files(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "x.mjs").write_text("const ROOT = '/repo';\n")
    diff = ("diff --git a/tools/x.mjs b/tools/x.mjs\n--- a/tools/x.mjs\n+++ b/tools/x.mjs\n"
            "@@ -1 +1 @@\n-a\n+b\n")
    ctx = vr.gather_file_context(diff, tmp_path)
    assert "const ROOT" in ctx               # the declaration the diff-only panel couldn't see
    assert "tools/x.mjs" in ctx


def test_gather_file_context_includes_anchors_and_skips_missing(tmp_path):
    (tmp_path / "package.json").write_text('{"engines": {"node": ">=22.12.0"}}')
    diff = ("diff --git a/missing.py b/missing.py\n--- a/missing.py\n+++ b/missing.py\n"
            "@@ -1 +1 @@\n-a\n+b\n")
    ctx = vr.gather_file_context(diff, tmp_path)
    assert ">=22.12.0" in ctx                # package.json anchor pulled in even if not in diff
    # a referenced-but-absent file must not raise
    assert "missing.py" not in ctx or ctx.count("missing.py") >= 0


def test_gather_file_context_caps_large_files(tmp_path):
    (tmp_path / "big.js").write_text("x" * 5000)
    diff = ("diff --git a/big.js b/big.js\n--- a/big.js\n+++ b/big.js\n@@ -1 +1 @@\n-a\n+b\n")
    ctx = vr.gather_file_context(diff, tmp_path, per_file_cap=1000)
    assert "truncated" in ctx                # truncate() marker, didn't dump the whole file
