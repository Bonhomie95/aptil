"""Detect which country a free-text job location names.

Job locations are unstructured strings — "Singapore, Singapore", "Remote, USA",
"Ho Chi Minh City, Vietnam", "London". To honour a user's chosen countries we
have to work out which country (if any) a location refers to, then drop the
ones outside their targets.

Deliberately conservative: a location that names NO country we recognise
(a bare city, "Remote") is left for the caller to keep, so we never over-filter
a US posting that simply failed to spell out "USA".
"""

from __future__ import annotations

import re

# ISO-2 code -> lowercase substrings that identify that country in a location
# string. Covers the countries the search targets support PLUS the ones that
# commonly show up in postings so we can recognise (and exclude) them. Ordered
# patterns are matched as whole words to avoid "us" hitting "Austin".
_COUNTRY_PATTERNS: dict[str, tuple[str, ...]] = {
    "us": ("united states", "usa", "u.s.a", "u.s.", "america", "us"),
    "gb": ("united kingdom", "uk", "u.k.", "england", "scotland", "wales", "london"),
    "ca": ("canada",),
    "au": ("australia", "sydney", "melbourne"),
    "nz": ("new zealand",),
    "ie": ("ireland", "dublin"),
    "de": ("germany", "berlin", "munich"),
    "fr": ("france", "paris"),
    "es": ("spain", "madrid", "barcelona"),
    "it": ("italy", "rome", "milan"),
    "nl": ("netherlands", "amsterdam"),
    "be": ("belgium", "brussels"),
    "ch": ("switzerland", "zurich", "geneva"),
    "at": ("austria", "vienna"),
    "pl": ("poland", "warsaw", "krakow"),
    "pt": ("portugal", "lisbon"),
    "se": ("sweden", "stockholm"),
    "br": ("brazil", "brasil", "sao paulo"),
    "mx": ("mexico", "méxico"),
    "in": ("india", "bangalore", "bengaluru", "mumbai", "hyderabad", "pune",
           "delhi", "chennai", "gurgaon", "noida"),
    "sg": ("singapore",),
    "vn": ("vietnam", "viet nam", "ho chi minh", "hanoi"),
    "ph": ("philippines", "manila"),
    "id": ("indonesia", "jakarta"),
    "my": ("malaysia", "kuala lumpur"),
    "jp": ("japan", "tokyo"),
    "cn": ("china", "beijing", "shanghai", "shenzhen"),
    "hk": ("hong kong",),
    "za": ("south africa", "johannesburg", "cape town"),
    "ng": ("nigeria", "lagos", "abuja"),
    "ke": ("kenya", "nairobi"),
    "eg": ("egypt", "cairo"),
    "ae": ("united arab emirates", "uae", "dubai", "abu dhabi"),
    "il": ("israel", "tel aviv"),
    "ar": ("argentina", "buenos aires"),
    "co": ("colombia", "bogota", "bogotá"),
    "cl": ("chile", "santiago"),
}


def detect_countries(location: str | None) -> set[str]:
    """ISO-2 codes a location string appears to name (may be empty)."""
    text = (location or "").lower()
    if not text:
        return set()
    hits: set[str] = set()
    for code, patterns in _COUNTRY_PATTERNS.items():
        for pat in patterns:
            # Whole-word / boundary match so "us" doesn't fire inside "Austin"
            # and "uk" doesn't fire inside "Paducah".
            if re.search(r"(?<![a-z])" + re.escape(pat) + r"(?![a-z])", text):
                hits.add(code)
                break
    return hits


def location_allowed(location: str | None, targets: set[str]) -> bool:
    """Whether a job's location is acceptable for a user targeting ``targets``.

    - No target countries set        -> everything allowed (caller not filtering).
    - Location names a target country -> allowed.
    - Location names ONLY non-target countries -> rejected.
    - Location names no country we recognise (bare city, "Remote") -> allowed,
      so a US posting written as "Austin, TX" is not thrown away.
    """
    if not targets:
        return True
    detected = detect_countries(location)
    if not detected:
        return True
    return bool(detected & targets)
