import pytest

from textkit import word_count


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", 0),
        ("   ", 0),
        ("hello world", 2),
        ("hello   world", 2),
        ("one\ntwo\tthree", 3),
        ("  leading and trailing  ", 3),
    ],
)
def test_word_count(text, expected):
    assert word_count(text) == expected
