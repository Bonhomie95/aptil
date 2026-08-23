"""Mapping stored EEO answers onto the labels employers actually render.

A miss here drops the user's answer. A WRONG hit reports a protected
characteristic incorrectly to an employer, which is far worse — so every case
below asserts the exact value, never merely "something was matched".

Label wording is taken from OFCCP Form CC-305 (OMB 1250-0005), the VEVRAA
self-identification form, and the EEO-1 race/ethnicity categories.
"""

from __future__ import annotations

import pytest

from app.models.profile import (
    DISABILITY_CHOICES,
    GENDER_CHOICES,
    RACE_CHOICES,
    VETERAN_CATEGORY_CHOICES,
    VETERAN_CHOICES,
)
from app.services.ats.base import CHOICE_LABELS, _best_value_for


# --- the two bugs that made this rewrite necessary ------------------------
def test_race_qualifier_does_not_hijack_the_category():
    """"(Not Hispanic or Latino)" qualifies the category; it is not the answer.

    Left in the haystack it is a longer match than the category itself, so
    "White (Not Hispanic or Latino)" scored as hispanic_or_latino.
    """
    for label, expected in [
        ("White (Not Hispanic or Latino)", "white"),
        ("Asian (Not Hispanic or Latino)", "asian"),
        ("Black or African American (Not Hispanic or Latino)",
         "black_or_african_american"),
        ("American Indian or Alaska Native (Not Hispanic or Latino)",
         "american_indian_or_alaska_native"),
        ("Native Hawaiian or Other Pacific Islander (Not Hispanic or Latino)",
         "native_hawaiian_or_pacific_islander"),
        ("Two or More Races (Not Hispanic or Latino)", "two_or_more_races"),
        ("Hispanic or Latino", "hispanic_or_latino"),
    ]:
        assert _best_value_for("race", label) == expected, label


def test_protected_veteran_is_not_confused_with_its_own_negation():
    """"protected veteran" is a substring of "I am not a protected veteran"."""
    assert _best_value_for(
        "veteran_status",
        "I identify as one or more of the classifications of a protected veteran",
    ) == "protected_veteran"
    assert _best_value_for(
        "veteran_status", "I AM NOT A PROTECTED VETERAN"
    ) == "not_a_veteran"


# --- CC-305 is a standardized federal form: wording is fixed --------------
@pytest.mark.parametrize(
    "label,expected",
    [
        ("Yes, I have a disability, or have had one in the past", "yes"),
        ("No, I do not have a disability and have not had one in the past", "no"),
        ("I do not want to answer", "do_not_want_to_answer"),
        # Older boards still ship the pre-2023 wording.
        ("YES, I HAVE A DISABILITY (or previously had a disability)", "yes"),
        ("NO, I DON'T HAVE A DISABILITY", "no"),
        ("I DON'T WISH TO ANSWER", "do_not_want_to_answer"),
    ],
)
def test_cc305_disability_options(label, expected):
    assert _best_value_for("disability_status", label) == expected


def test_no_disability_is_never_read_as_yes():
    """The 'no' option contains the word 'have' and the phrase 'had one in the
    past'; a sloppy matcher reads it as a disclosure."""
    label = "No, I do not have a disability and have not had one in the past"
    assert _best_value_for("disability_status", label) != "yes"


@pytest.mark.parametrize(
    "label",
    ["Decline To Self Identify", "I don't wish to answer", "Prefer not to say",
     "I do not wish to answer", "Decline to self-identify"],
)
def test_every_decline_wording_is_recognised(label):
    assert _best_value_for("gender", label) == "decline_to_self_identify"


# --- the tables agree with the model -------------------------------------
@pytest.mark.parametrize(
    "field,choices",
    [
        ("gender", GENDER_CHOICES),
        ("race", RACE_CHOICES),
        ("veteran_status", VETERAN_CHOICES),
        ("disability_status", DISABILITY_CHOICES),
    ],
)
def test_every_stored_value_can_be_filled(field, choices):
    """A value the model accepts but the filler cannot place would be collected
    from the user and then silently dropped on every form."""
    missing = [c for c in choices if not CHOICE_LABELS.get(field, {}).get(c)]
    assert not missing, f"{field} has unfillable values: {missing}"


def test_vevraa_has_all_four_protected_classifications():
    assert len(VETERAN_CATEGORY_CHOICES) == 4
    assert set(VETERAN_CATEGORY_CHOICES) == {
        "disabled_veteran",
        "recently_separated_veteran",
        "active_duty_wartime_or_campaign_badge_veteran",
        "armed_forces_service_medal_veteran",
    }
