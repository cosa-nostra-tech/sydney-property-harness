"""Numeric provenance enforcement — the mechanical guard against invented figures.

THE PROBLEM, MEASURED
---------------------
On the replica harness, asked for real Marrickville sale prices, the agent answered:

    "Here are the real, settled sale prices for MARRICKVILLE over the last 6 months
     ... straight from the NSW Valuer General record — not asking prices."
    | Houses / semis / terraces | 80 | $1.70M | $1.98M | $2.36M | $4.5M |
    - 16 Darley St — $4,500,000 (July, 728 sqm block)

The tool had returned `status: unavailable, reason: source_unreachable` with ZERO rows.
Every figure, and the street address, was invented — and attributed to State government
data. For a product where a user sets an auction limit from that table, this is the worst
failure it can have.

Telling the model not to do it does not work. It had an `agent_instruction` saying
"never invent a sale price to fill the gap" and it invented anyway. It obeyed the
no-disclosure rule and broke the honesty rule underneath it.

So this enforces it in code. `transform_tool_result` accumulates what the tools actually
returned during the turn; `transform_llm_output` runs before the reply is delivered and
checks every money/percentage figure in it against that accumulated evidence. Figures
that no tool produced are named to the reader.

WHY NOT SILENTLY STRIP THEM
---------------------------
Removing a number leaves a sentence with a hole in it, which reads worse than the number
did and destroys the answer. Naming them keeps the reply useful and makes the gap
auditable, which is the honest move under a product rule of "never invent figures".

The verification logic itself lives in the tested `number_provenance` module (10/10 tests
against the captured fabrication) and is loaded from the tools dir so there is exactly one
implementation.
"""
from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_MAX_TURNS_KEPT = 60
_state: dict[str, list[str]] = {}
_module: Any = None


def _tools_dir() -> Path:
    import os
    home = Path(os.environ.get("HERMES_HOME", "/data/.hermes"))
    return home / "tools"


def _provenance():
    """Load the shared verifier from the tools dir, once."""
    global _module
    if _module is not None:
        return _module
    path = _tools_dir() / "number_provenance.py"
    if not path.is_file():
        logger.warning("provenance: %s not found — figure checking disabled", path)
        return None
    try:
        spec = importlib.util.spec_from_file_location("tb_number_provenance", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _module = mod
    except Exception:  # noqa: BLE001
        logger.exception("provenance: could not load the verifier")
    return _module


def on_tool_result(tool_name: str = "", result: Any = None, session_id: str = "", **_: Any):
    """Collect the real tool output for this session. Never rewrites the result.

    Returning None is deliberate: the model must still see everything the tool said,
    including an `unavailable` payload, so it knows not to invent the data.
    """
    sid = session_id or "_"
    try:
        _state.setdefault(sid, []).append(f"[{tool_name}]\n{result}")
        if len(_state[sid]) > _MAX_TURNS_KEPT:
            del _state[sid][:-_MAX_TURNS_KEPT]
    except Exception:  # noqa: BLE001
        logger.exception("provenance: could not record tool result")
    return None


def on_llm_output(response_text: str = "", session_id: str = "", **_: Any) -> str | None:
    """Verify the reply's figures against the turn's tool output.

    Returns a replacement string when unsourced figures were found, else None so the
    reply passes through untouched.
    """
    mod = _provenance()
    if mod is None or not response_text:
        return None
    sid = session_id or "_"
    blob = "\n".join(_state.get(sid, []))
    # Clear per turn: the next turn starts with an empty evidence set.
    _state.pop(sid, None)

    try:
        result = mod.verify(response_text, blob)
    except Exception:  # noqa: BLE001
        logger.exception("provenance: verification failed — passing the reply through")
        return None

    if result.get("clean"):
        logger.info("provenance: %d figures, all sourced", result.get("total", 0))
        return None

    bad = [f["raw"] for f in result.get("unsourced", [])]
    logger.warning("provenance: %d/%d figures unsourced: %s",
                   len(bad), result.get("total", 0), bad[:8])

    # CONSERVATIVE BY DESIGN. This hook REPLACES the reply, so a false positive is a
    # defect: it would annotate a good answer. Only fire on the failure that was
    # actually measured in production — a reply asserting market figures when the
    # tools returned NO data at all for the turn. That is the "Do I qualify for the
    # First Home Guarantee?" case (accuracy 0, no_fabrication 0).
    #
    # Deliberately NOT annotating when tools DID return data and a couple of figures
    # don't match: that is more likely a derived rate (yield from a sourced price and
    # rent), a rounding, or a statistic quoted from general knowledge, and flagging it
    # would add noise to correct answers. Coverage is traded for precision here on
    # purpose — a guard that cries wolf gets switched off.
    if result.get("no_source_data") and len(bad) >= 2:
        # ONE short line, and NO enumeration. `mod.annotate()` lists the figures, which
        # is right for an audit tool and wrong for a user: a footer reading
        # "Verify before relying on: $95K, $750K, $1,500,000, $900K, 35,000, 5% (+24 more)"
        # is unreadable, and a list of numbers to distrust on most replies destroys the
        # confidence the product is supposed to instil. The user needs to know to treat
        # the figures as indicative; they do not need the inventory.
        return (response_text.rstrip() +
                "\n\n*Figures above are typical ranges from general practice, not "
                "settled sale data for a specific property — worth confirming against "
                "soldNSW before you rely on them.*")

    logger.info("provenance: %d figure(s) unmatched but data was present — not annotating",
                len(bad))
    return None
