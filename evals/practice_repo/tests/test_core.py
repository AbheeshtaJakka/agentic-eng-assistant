from textkit import truncate, word_count


def test_word_count_simple():
    assert word_count("hello world") == 2


def test_truncate_short_text_unchanged():
    assert truncate("hi", 10) == "hi"
