"""Split a review into numbered evidence segments that are exact substrings of the original text."""

import re

# A boundary is a line break, or sentence-ending punctuation followed by whitespace.
_BOUNDARY = re.compile(r"\n+|(?<=[.!?])\s+")


def segments(text):
    """Return the non-blank segments of `text`, each stripped and guaranteed to be a substring of `text`."""
    parts = [p.strip() for p in _BOUNDARY.split(text)]
    parts = [p for p in parts if p]
    assert all(p in text for p in parts)
    return parts or [text]


def render_review(number, text):
    """Format one review the way the enrichment prompt expects: '#n' then '<k> segment' lines."""
    lines = [f"#{number}"]
    lines += [f"<{k}> {seg}" for k, seg in enumerate(segments(text), 1)]
    return "\n".join(lines)
