import pytest


@pytest.mark.parametrize("path, expected", [
    ("README.md",          "readme"),
    ("docs/api.md",        "api_reference"),
    ("docs/auth/login.md", "authentication"),
    ("config/settings.md", "configuration"),
    ("docs/guide.md",      "guide"),
    ("docs/deploy.md",     "deployment"),
    ("CHANGELOG.md",       "changelog"),
    ("notes.md",           "general"),
])
def test_classify_doc(path, expected):
    from app.services.doc_types import classify_doc
    assert classify_doc(path) == expected


def test_feedback_and_doc_writer_share_one_classifier():
    """A correction is stored by feedback and looked up by the doc writer;
    if the two ever classify differently, the lookup silently misses."""
    from app.agents import doc_writer
    from app.services import doc_types, feedback
    assert feedback.classify_doc is doc_types.classify_doc
    assert doc_writer.classify_doc is doc_types.classify_doc
