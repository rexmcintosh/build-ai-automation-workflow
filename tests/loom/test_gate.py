from loom.gate import scan_clean


def test_clean_text_passes(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("the quick brown fox jumped over the lazy dog")
    assert scan_clean(f) is True


def test_aws_key_is_caught(tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("aws_secret = 'AKIAIOSFODNN7EXAMPLE'\nkey='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'\n")
    assert scan_clean(f) is False


def test_nonexistent_file_is_refused(tmp_path):
    assert scan_clean(tmp_path / "does_not_exist.txt") is False


def test_directory_is_refused(tmp_path):
    d = tmp_path / "adir"
    d.mkdir()
    assert scan_clean(d) is False


def test_benign_high_entropy_ids_pass(tmp_path):
    f = tmp_path / "ids.txt"
    f.write_text(
        "Gmail thread 19e3fcd6543b7ddf\n"
        "Drive doc 1lDZfHGHj_N8dWPg3l3HZ4Si_gs_PZDdYPBgqXfCTA7s\n"
        "just some ordinary notes about the project\n"
    )
    assert scan_clean(f) is True
