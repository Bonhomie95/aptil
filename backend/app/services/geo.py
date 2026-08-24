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
# --- Search-target countries (for the location picker) ----------------------
#
# Web search can target ANY country by putting its name in the query, so this is
# simply a curated list of major job markets the picker offers — not a hard
# limit. Expand freely.
SEARCH_COUNTRIES: dict[str, str] = {
    "us": "United States", "ca": "Canada", "gb": "United Kingdom",
    "ie": "Ireland", "au": "Australia", "nz": "New Zealand",
    "de": "Germany", "fr": "France", "es": "Spain", "it": "Italy",
    "nl": "Netherlands", "be": "Belgium", "ch": "Switzerland",
    "at": "Austria", "pl": "Poland", "pt": "Portugal", "se": "Sweden",
    "no": "Norway", "dk": "Denmark", "fi": "Finland",
    "in": "India", "sg": "Singapore", "ae": "United Arab Emirates",
    "jp": "Japan", "br": "Brazil", "mx": "Mexico", "za": "South Africa",
    "ng": "Nigeria", "ke": "Kenya",
}

# Continent groupings so a user can pick a region instead of ticking countries.
CONTINENTS: dict[str, list[str]] = {
    "north_america": ["us", "ca", "mx"],
    "south_america": ["br"],
    "europe": ["gb", "ie", "de", "fr", "es", "it", "nl", "be", "ch", "at",
               "pl", "pt", "se", "no", "dk", "fi"],
    "asia": ["in", "sg", "ae", "jp"],
    "oceania": ["au", "nz"],
    "africa": ["za", "ng", "ke"],
}


def resolve_countries(values: list[str]) -> list[str]:
    """Expand a mix of ISO-2 codes and continent names into valid ISO-2 codes.

    Unknown entries are dropped, order preserved, deduped. So the UI can send
    ["europe", "us"] and get every European country plus the US.
    """
    out: list[str] = []
    for raw in values or []:
        key = str(raw).strip().lower()
        if key in CONTINENTS:
            out.extend(CONTINENTS[key])
        elif key in SEARCH_COUNTRIES:
            out.append(key)
    seen: set[str] = set()
    return [c for c in out if not (c in seen or seen.add(c))]


_COUNTRY_PATTERNS: dict[str, tuple[str, ...]] = {
    # Major job markets get city aliases too, so "Austin, TX" style US postings
    # and "Bangalore" style India postings are recognised without a country
    # word. Every other country is matched by its name(s), which job locations
    # almost always include ("Lima, Peru", "Quito, Ecuador").
    "us": ("united states", "usa", "u.s.a", "u.s.", "america", "us"),
    "gb": ("united kingdom", "uk", "u.k.", "england", "scotland", "wales",
           "london", "britain", "northern ireland"),
    "ca": ("canada", "toronto", "vancouver", "montreal"),
    "au": ("australia", "sydney", "melbourne", "brisbane"),
    "nz": ("new zealand", "auckland"),
    "ie": ("ireland", "dublin"),
    "de": ("germany", "berlin", "munich", "hamburg", "deutschland"),
    "fr": ("france", "paris", "lyon"),
    "es": ("spain", "madrid", "barcelona", "espana"),
    "it": ("italy", "rome", "milan", "italia"),
    "nl": ("netherlands", "amsterdam", "holland"),
    "be": ("belgium", "brussels"),
    "ch": ("switzerland", "zurich", "geneva"),
    "at": ("austria", "vienna"),
    "pl": ("poland", "warsaw", "krakow"),
    "pt": ("portugal", "lisbon"),
    "se": ("sweden", "stockholm"),
    "no": ("norway", "oslo"),
    "dk": ("denmark", "copenhagen"),
    "fi": ("finland", "helsinki"),
    "in": ("india", "bangalore", "bengaluru", "mumbai", "hyderabad", "pune",
           "delhi", "chennai", "gurgaon", "noida", "kolkata"),
    "sg": ("singapore",),
    "vn": ("vietnam", "viet nam", "ho chi minh", "hanoi"),
    "ph": ("philippines", "manila", "cebu"),
    "id": ("indonesia", "jakarta"),
    "my": ("malaysia", "kuala lumpur"),
    "th": ("thailand", "bangkok"),
    "jp": ("japan", "tokyo", "osaka"),
    "kr": ("south korea", "korea", "seoul"),
    "cn": ("china", "beijing", "shanghai", "shenzhen"),
    "hk": ("hong kong",),
    "tw": ("taiwan", "taipei"),
    "za": ("south africa", "johannesburg", "cape town", "pretoria"),
    "ng": ("nigeria", "lagos", "abuja"),
    "ke": ("kenya", "nairobi"),
    "gh": ("ghana", "accra"),
    "eg": ("egypt", "cairo"),
    "ma": ("morocco", "casablanca"),
    "ae": ("united arab emirates", "uae", "dubai", "abu dhabi"),
    "sa": ("saudi arabia", "riyadh", "jeddah"),
    "il": ("israel", "tel aviv"),
    "tr": ("turkey", "istanbul", "ankara", "turkiye"),
    "ar": ("argentina", "buenos aires"),
    "co": ("colombia", "bogota", "bogotá", "medellin"),
    "cl": ("chile", "santiago"),
    "pe": ("peru", "lima"),
    "ec": ("ecuador", "quito", "guayaquil"),
    "br": ("brazil", "brasil", "sao paulo", "rio de janeiro"),
    "mx": ("mexico", "méxico", "mexico city", "guadalajara"),
    "uy": ("uruguay", "montevideo"),
    "py": ("paraguay",),
    "bo": ("bolivia",),
    "ve": ("venezuela", "caracas"),
    "cr": ("costa rica", "san jose"),
    "pa": ("panama",),
    "gt": ("guatemala",),
    "do": ("dominican republic",),
    "cz": ("czech republic", "czechia", "prague"),
    "sk": ("slovakia", "bratislava"),
    "hu": ("hungary", "budapest"),
    "ro": ("romania", "bucharest"),
    "bg": ("bulgaria", "sofia"),
    "gr": ("greece", "athens"),
    "hr": ("croatia", "zagreb"),
    "rs": ("serbia", "belgrade"),
    "ua": ("ukraine", "kyiv", "kiev"),
    "ru": ("russia", "moscow"),
    "ee": ("estonia", "tallinn"),
    "lv": ("latvia", "riga"),
    "lt": ("lithuania", "vilnius"),
    "is": ("iceland", "reykjavik"),
    "lu": ("luxembourg",),
    "pk": ("pakistan", "karachi", "lahore"),
    "bd": ("bangladesh", "dhaka"),
    "lk": ("sri lanka", "colombo"),
    "np": ("nepal", "kathmandu"),
    "qa": ("qatar", "doha"),
    "kw": ("kuwait",),
    "bh": ("bahrain",),
    "om": ("oman",),
    "jo": ("jordan", "amman"),
    "lb": ("lebanon", "beirut"),
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
