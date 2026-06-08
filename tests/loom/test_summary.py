# tests/loom/test_summary.py
from loom.summary import build_summary, scrub


def test_build_summary_lists_counts_and_rejections():
    s = build_summary(
        counts={"distilled": 2, "committed": 5, "deferred": 1, "rejected": 1,
                "quarantined": 0, "failed": 0},
        shadow_commits=6, oldest_age_days=3,
        rejected=[("s1#0", "sentinel hit: pipe-to-shell")],
        proposed=["CLAUDE.md: add note about X"],
    )
    assert "committed=5" in s and "deferred=1" in s
    assert "s1#0" in s and "sentinel" in s
    assert "loom-shadow" in s and "3" in s
    assert "CLAUDE.md" in s


def test_scrub_redacts_secret_patterns():
    out = scrub("token AKIAIOSFODNN7EXAMPLE here")
    assert "AKIA" not in out and "<redacted>" in out


def test_staleness_threshold_flags_old_shadow():
    s = build_summary(counts={"committed": 0}, shadow_commits=4, oldest_age_days=10,
                      rejected=[], proposed=[])
    assert "STALE" in s
