#!/usr/bin/env python3
"""
record_screening_tool.py — the screening signal, and the unit the product bills on.

THE MECHANISM
The unit we charge for is one screening: the user asks Luca to screen a specific address
and Luca completes it. That has to be a hard, countable event rather than something inferred
from the wording of a reply, so the model calls this tool exactly once when a screening is
finished.

WHAT THIS TOOL DOES: returns a receipt. It writes no rows, gates nothing and holds no
credentials, because the harness should not have database access. The gateway already emits
a standard `tool.progress` event carrying each tool's name, so /api/chat — which is proxying
that stream anyway, to drive the thinking panel — watches for this tool's name and writes one
`usage_events` row. The allowance is enforced there too.

WHY NOT A MARKER IN THE REPLY
A sentence can be omitted, repeated or reworded by the model on any given turn. A tool call
is a discrete event the gateway reports. Counting on prose would mean billing on a guess.

WHY THE MODEL MUST NOT NARRATE THIS
The user should never see "this screening has been recorded" or any charge language. The
tool returns a receipt to the model, SOUL.md instructs it to say nothing about it, and the
reply reads exactly as it would have without the mechanism.
"""

from __future__ import annotations

import json
import logging
import re
import sys

logger = logging.getLogger(__name__)


_ABBREV = {
    "rd": "road", "st": "street", "ave": "avenue", "av": "avenue", "pde": "parade",
    "cres": "crescent", "hwy": "highway", "pl": "place", "dr": "drive", "ct": "court",
    "tce": "terrace", "ln": "lane", "cl": "close", "gr": "grove", "blvd": "boulevard",
    "esp": "esplanade", "circ": "circuit", "gdns": "gardens",
}


def _address_key(address: str) -> str:
    """Normalise an address so the same property screened twice is one credit.

    Matches the unique index on (user_id, address_key) in usage_events: the database is the
    final arbiter, this just makes the two agree.
    """
    a = (address or "").lower()
    a = re.sub(r"\b(nsw|australia|au)\b", " ", a)
    a = re.sub(r"\b\d{4}\b", " ", a)          # postcode
    a = re.sub(r"[^a-z0-9]+", " ", a)
    for short, full in _ABBREV.items():
        a = re.sub(rf"\b{short}\b", full, a)
    return " ".join(a.split())


def record_screening(address: str) -> dict:
    """Acknowledge that a full screening of this address has been completed."""
    addr = (address or "").strip()
    if not addr:
        return {
            "recorded": False,
            "reason": "No address given. A screening is counted against a specific property.",
        }
    return {
        "recorded": True,
        "kind": "screening",
        "address": addr,
        "address_key": _address_key(addr),
        "note": "Receipt only. Do not mention this to the user or describe it in the reply.",
    }


def _schema() -> dict:
    return {
        "name": "record_screening",
        "description": (
            "Record that Luca has completed a full screening of one property address. "
            "Call this exactly once, after the screening is finished, when the user asked "
            "for that property to be screened. Do not call it for general questions, "
            "suburb research, or a property the user has not asked to be screened. "
            "Never mention this call or its result to the user."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": (
                        "The full street address that was screened, as the user framed it. "
                        "Include the street, suburb and state where known — for example "
                        "'14 Addison Road Marrickville NSW'."
                    ),
                }
            },
            "required": ["address"],
        },
    }


try:
    from tools.registry import registry  # type: ignore

    registry.register(
        name="record_screening",
        schema=_schema(),
        handler=lambda args, **kw: json.dumps(
            record_screening(args.get("address", "")), indent=2
        ),
        check_fn=lambda: True,
        requires_env=[],
    )
except ImportError:
    pass


if __name__ == "__main__":
    addr = sys.argv[1] if len(sys.argv) > 1 else "14 Addison Road Marrickville NSW"
    print(json.dumps(record_screening(addr), indent=2))


# Self-check: the normaliser must treat the same property as one credit.
def _selfcheck() -> None:
    same = [
        "14 Addison Road Marrickville NSW 2204",
        "14 addison road, marrickville nsw",
        "14 Addison Rd Marrickville",
    ]
    keys = {_address_key(a) for a in same}
    assert len(keys) == 1, f"normaliser split one property into {keys}"
    assert _address_key("9 Illawarra Rd Marrickville") != _address_key(
        "14 Addison Road Marrickville NSW 2204"
    ), "normaliser merged two different properties"
    print("  address_key normalisation: ok")


if __name__ == "__main__" and "--selfcheck" in sys.argv:
    _selfcheck()
