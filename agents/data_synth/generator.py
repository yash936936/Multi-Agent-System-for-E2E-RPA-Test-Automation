"""
DataSynth.generate implementation.

Produces realistic values (via Faker) for normal data_requirements fields,
plus deliberate edge-case values for any field flagged as an edge case by
the Planner (see agents/planner/spec_generator.py's `_EDGE_CASE_HINTS`
detection — fields prefixed `edge_case_`).

Matches PRD FR4: synthetic test data must include both realistic values
and boundary/malformed cases to properly exercise input handling.
"""
from __future__ import annotations

import random
import string

from faker import Faker

_fake = Faker()

# Recognized "normal" field name -> generator function
_FIELD_GENERATORS = {
    "username": lambda: _fake.user_name(),
    "email": lambda: _fake.email(),
    "password": lambda: _fake.password(length=14, special_chars=True, digits=True, upper_case=True, lower_case=True),
    "name": lambda: _fake.name(),
    "phone": lambda: _fake.phone_number(),
    "address": lambda: _fake.address().replace("\n", ", "),
    "date_of_birth": lambda: _fake.date_of_birth().isoformat(),
    "dob": lambda: _fake.date_of_birth().isoformat(),
    "zip": lambda: _fake.postcode(),
    "postal_code": lambda: _fake.postcode(),
    "credit_card": lambda: _fake.credit_card_number(),
}

# Edge-case suffix -> generator function. Field names look like
# "edge_case_unicode_name" or "edge_case_max_length" per the Planner's slugging.
_EDGE_CASE_GENERATORS = {
    "unicode": lambda: "Zoë Müller 松本 🚀",
    "unicode_name": lambda: "Zoë Müller 松本 🚀",
    "max_length": lambda: "".join(random.choices(string.ascii_letters + string.digits, k=255)),
    "boundary": lambda: "".join(random.choices(string.ascii_letters + string.digits, k=255)),
    "malformed": lambda: "not-an-email@@@..bad",
    "special_character": lambda: "!@#$%^&*()_+-=[]{}|;':\",./<>?`~",
}


def _generate_value(field: str) -> str:
    field_norm = field.strip().lower()

    if field_norm.startswith("edge_case_"):
        suffix = field_norm[len("edge_case_"):]
        for key, gen in _EDGE_CASE_GENERATORS.items():
            if key in suffix:
                return gen()
        # unrecognized edge-case suffix: fall back to a generic malformed string
        return _EDGE_CASE_GENERATORS["malformed"]()

    if field_norm in _FIELD_GENERATORS:
        return _FIELD_GENERATORS[field_norm]()

    # unrecognized normal field: generate a plausible generic word/phrase
    return _fake.word()


def generate_data(fields: list[str]) -> dict[str, str]:
    return {field: _generate_value(field) for field in fields}


def generate_value(field: str) -> str:
    """
    Public single-field wrapper around _generate_value() (D-045) -- added
    so other modules (agents/vision/form_fuzzer.py) can reuse this
    module's realistic/edge-case generation without importing a private
    (underscore-prefixed) function, per context.md §6's rule to reuse
    existing code rather than re-implement it, without breaking this
    module's own naming convention for what's public.
    """
    return _generate_value(field)
