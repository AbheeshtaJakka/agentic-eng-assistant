import pytest

from textkit import slugify


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello, World!", "hello-world"),
        ("  Multi   Agent__SDK  ", "multi-agent-sdk"),
        ("", ""),
        ("---", ""),
        ("Already-a-slug", "already-a-slug"),
        ("Python 3.12 release", "python-3-12-release"),
    ],
)
def test_slugify(text, expected):
    assert slugify(text) == expected
