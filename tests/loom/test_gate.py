from loom.gate import scan_clean


def test_clean_text_passes(tmp_path):
    f = tmp_path / "c.txt"
    f.write_text("the quick brown fox jumped over the lazy dog")
    assert scan_clean(f) is True


def test_aws_key_is_caught(tmp_path):
    f = tmp_path / "d.txt"
    f.write_text("aws_secret = 'AKIAIOSFODNN7EXAMPLE'\nkey='wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'\n")
    assert scan_clean(f) is False
