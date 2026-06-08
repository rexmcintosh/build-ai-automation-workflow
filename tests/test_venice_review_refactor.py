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
