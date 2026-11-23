from textkit import truncate


def test_result_never_exceeds_max_len():
    for n in range(0, 15):
        assert len(truncate("hello world, this is long", n)) <= n


def test_example_from_issue():
    assert truncate("hello world", 8) == "hello..."


def test_short_text_unchanged():
    assert truncate("hi", 10) == "hi"
    assert truncate("exactly10!", 10) == "exactly10!"


def test_custom_suffix():
    assert truncate("abcdefghij", 6, suffix="~") == "abcde~"


def test_max_len_smaller_than_suffix():
    assert truncate("abcdefghij", 2) == ".."
