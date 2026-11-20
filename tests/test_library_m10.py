"""M10 knowledge files: each phrase supports one rule of v0.2 (see .planning/M10_SOURCES.md)."""
from pathlib import Path

import pytest

LIB = Path(__file__).parents[1] / "src" / "frecklebubby" / "data" / "library"

PHRASES = [
    ("who-under-5-activity-sleep", "For infants not yet mobile, this includes at least 30 minutes in prone position (tummy time)"),
    ("nhs-physical-activity-under-5", "Try to include at least 30 minutes of tummy time spread throughout the day when they're awake."),
    ("who-under-5-activity-sleep", "should not be restrained for more than 1 hour at a time"),
    ("who-under-5-activity-sleep", "WHO counts time restrained in car seats, high chairs, strollers"),
    ("nhs-keep-baby-active", "it's best to use them for no more than 20 minutes at a time"),
    ("nhs-keep-baby-active", "being strapped into a buggy, car seat or highchair – is not good for young children"),
    ("car-seat-time", "Frecklebubby found no official source that sets a 2-hour limit for car seat use."),
    ("car-seat-time", "take a break every 2 to 3 hours on a day trip"),
    ("car-seat-time", "The Lullaby Trust (UK charity) gives no number of hours."),
    ("nhs-nappy-rash", "leave nappies off when possible"),
    ("nhs-nappy-rash", "change wet or dirty nappies as soon as possible"),
    ("nhs-nappy-rash", "your baby's nappy rash does not go away, gets worse or spreads to other areas"),
    ("nhs-nappy-rash", "your baby has a high temperature"),
    ("nhs-nappy-rash", "your baby seems very uncomfortable"),
    ("nhs-nappies-and-poo", "Wearing a nappy all the time makes nappy rash more likely."),
    ("nhs-dehydration", "dark yellow, strong-smelling pee"),
    ("nhs-dehydration", "fewer wet nappies than usual"),
    ("nhs-newborn-jaundice", "their pee is dark yellow or brown or their poo is a pale creamy colour"),
    ("nhs-nappies-and-poo", "If your baby's poos look pale, this can be a sign of jaundice."),
    ("nhs-rectal-bleeding", "See a GP if your child has blood in their poo."),
    ("nhs-rectal-bleeding", "your poo is black or dark red"),
    ("nhs-blood-in-urine", "Blood in your pee may be bright pink, red or dark brown."),
]


@pytest.mark.parametrize(("name", "phrase"), PHRASES)
def test_phrase_is_in_file(name, phrase):
    assert phrase in (LIB / f"{name}.md").read_text(encoding="utf-8")
