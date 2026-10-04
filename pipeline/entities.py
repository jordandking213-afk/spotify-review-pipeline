"""Deterministic entity extraction (decision 8): match a fixed vocabulary of product-feature terms.

Only terms literally present in the text are returned, so nothing can be invented. Synonyms outside the
vocabulary are missed by design.
"""

import re

VOCABULARY = {
    "ads": r"\bads?\b|\badverti[sz]e?ments?\b|\bcommercials?\b",
    "lyrics": r"\blyrics?\b",
    "shuffle": r"\bshuffl\w*",
    "skip": r"\bskip\w*",
    "repeat": r"\brepeat\w*|\breplay\w*",
    "offline": r"\boffline\b|\boff line\b",
    "download": r"\bdownload\w*",
    "login": r"\blog ?in\w*|\blogged (in|out)\b|\bsign ?in\b|\bpassword\b",
    "account": r"\baccounts?\b",
    "premium": r"\bpremium\b",
    "subscription": r"\bsubscri\w*",
    "price": r"\bprices?\b|\bpricing\b|\bexpensive\b",
    "charge": r"\bcharg\w*|\brefund\w*|\bbill(ed|ing)\b",
    "podcast": r"\bpodcasts?\b",
    "playlist": r"\bplaylists?\b|\bplay list\b",
    "queue": r"\bqueue\w*",
    "search": r"\bsearch\w*",
    "recommendations": r"\brecommend\w*|\bsuggestions?\b|\balgorithm\b",
    "crash": r"\bcrash\w*",
    "update": r"\bupdat\w*",
    "support": r"\bsupport\b|\bcustomer (service|care)\b",
    "car": r"\bcars?\b|\bandroid auto\b|\bcarplay\b",
    "bluetooth": r"\bbluetooth\b",
    "audiobook": r"\baudio ?books?\b",
    "widget": r"\bwidgets?\b",
}
_COMPILED = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in VOCABULARY.items()}


def extract(text):
    """Return vocabulary terms found in `text`, in a stable (vocabulary) order."""
    return [name for name, pattern in _COMPILED.items() if pattern.search(text)]
