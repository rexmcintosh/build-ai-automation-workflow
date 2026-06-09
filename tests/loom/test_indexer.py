# tests/loom/test_indexer.py
from pathlib import Path
from loom.indexer import rebuild_backlinks, upsert_index_entry, SECTION_FOR, clean_summary
import json


def _article(root, rel, body):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)


def test_rebuild_backlinks_reverse_maps_wikilinks(tmp_path):
    _article(tmp_path, "people/liam.md", "# Liam\nSon of [[rex-mcintosh]]; see [[portugal]].\n")
    _article(tmp_path, "people/rex-mcintosh.md", "# Rex\nFather of [[liam]].\n")
    rebuild_backlinks(tmp_path)
    data = json.loads((tmp_path / "_backlinks.json").read_text())
    assert data["rex-mcintosh"] == ["liam"]
    assert sorted(data["liam"]) == ["rex-mcintosh"]
    assert data["portugal"] == ["liam"]


def test_section_for_known_dirs():
    assert SECTION_FOR["people"] == "People"
    assert SECTION_FOR["decisions"] == "Decisions"


def test_upsert_index_entry_adds_under_section(tmp_path):
    (tmp_path / "_index.md").write_text(
        "---\ntitle: \"_index\"\ntotal_pages: 1\n---\n\n# RexBrain — Master Index\n\n## People\n- [[rex-mcintosh]] — Rex.\n"
    )
    upsert_index_entry(tmp_path, "liam", "people", "Rex's son; competitive swimmer.", today="2026-06-08")
    txt = (tmp_path / "_index.md").read_text()
    assert "- [[liam]] — Rex's son; competitive swimmer." in txt
    assert txt.index("## People") < txt.index("[[liam]]")


def test_upsert_index_entry_is_idempotent(tmp_path):
    (tmp_path / "_index.md").write_text("# RexBrain — Master Index\n\n## People\n- [[rex-mcintosh]] — Rex.\n")
    for _ in range(2):
        upsert_index_entry(tmp_path, "liam", "people", "Son.", today="2026-06-08")
    assert (tmp_path / "_index.md").read_text().count("[[liam]]") == 1


def test_clean_summary_truncates_at_word_boundary():
    short = "A concise summary."
    assert clean_summary(short) == short                       # under limit, unchanged
    long = ("The only Hermes reference under projects is the hermes-parser package inside "
            "finance-tracker node_modules and it is a transitive dependency")
    out = clean_summary(long)
    assert out.endswith("…") and len(out) <= 111
    assert not out[:-1].endswith(" ")                          # no trailing space before ellipsis
    assert out[:-1] in long or long.startswith(out[:-1])       # it's a clean prefix, not mid-word garbage
    # collapses internal whitespace/newlines
    assert clean_summary("a\n\n  b   c") == "a b c"


def test_upsert_increments_total_pages(tmp_path):
    (tmp_path / "_index.md").write_text(
        "---\ntotal_pages: 26\n---\n\n# RexBrain — Master Index\n\n> ... Total pages: 26\n\n## People\n"
    )
    upsert_index_entry(tmp_path, "liam", "people", "Rex's son.", today="2026-06-09")
    txt = (tmp_path / "_index.md").read_text()
    assert "total_pages: 27" in txt          # frontmatter bumped
    assert "Total pages: 27" in txt          # intro line bumped
