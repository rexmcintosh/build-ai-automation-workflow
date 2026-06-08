# tests/loom/test_summary.py
from loom.summary import build_summary, scrub, format_run_summary


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


def test_build_summary_scrubs_secrets_in_items():
    fake_pat = "ghp_" + "a" * 36
    pem = "-----BEGIN PRIVATE KEY-----"
    s = build_summary(
        counts={"committed": 1},
        shadow_commits=1, oldest_age_days=0,
        rejected=[("s1#0", f"leaked {fake_pat}")],
        proposed=[f"note {pem} MIIB..."],
    )
    assert fake_pat not in s and "ghp_" not in s
    assert "-----BEGIN PRIVATE KEY-----" not in s
    assert "<redacted>" in s


def test_format_run_summary_from_absorb_dict():
    d = {"committed": 2, "deferred": 1, "rejected": 1,
         "rejected_items": [["s1#0", "sentinel hit"]],
         "shadow_commits": 5, "oldest_age_days": 9}
    s = format_run_summary(d)
    assert "committed=2" in s and "s1#0" in s and "STALE" in s and "5 commits" in s
