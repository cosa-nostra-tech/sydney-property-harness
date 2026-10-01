"""Fabrication guard: check a reply's figures against the data the turn actually retrieved.

WHY IT LIVES IN THE HARNESS
Both halves of the check exist in-process here: `transform_tool_result` sees every tool
result the model is given, and `transform_llm_output` sees the finished reply. An earlier
version tried to capture the sources to a file for an external script to read — but that
file was inside the harness container's own volume, unreachable from the builder box, so
the capture was designed to be unretrievable. Keeping the check here removes the problem
rather than working around it, and it is where the guard has to live in production anyway.

HOW IT DECIDES
Jev (TypeSafe) via the Noul primitive: "every dollar figure and percentage in the reply
appears in, or is directly derived from, the source data". Noul returns the probability
that the answer is YES, so a LOW value is a suspected fabrication. Measured separation on
a single swapped figure in otherwise identical prose: 0.960 faithful vs 0.020 invented.

WHAT IT DOES TO THE REPLY: NOTHING. This build is MEASURE-ONLY — `transform_llm_output`
always returns None, so the reply the user receives is byte-for-byte what it would have
been. The false-positive rate is not yet known, and a guard that blunts good answers would
cost the user confidence for no gain. Measure first, then decide the intervention.

WHERE THE RESULT GOES
A compact one-line record to stdout (readable in the Railway deploy logs) plus a JSONL under
the harness's own /data. No disclaimer, no footer, no user-visible artefact of any kind.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

TYPESAFE_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = os.environ.get("TRIGGERBOFF_GUARD_MODEL", "jev-latest")
LOG_PATH = os.environ.get("TRIGGERBOFF_GUARD_LOG", "/data/.hermes/provenance_guard.jsonl")
# Below this, the reply is a suspected fabrication. Kept conservative: we would rather
# miss a fabrication than blunt a good answer while the rates are being measured.
THRESHOLD = float(os.environ.get("TRIGGERBOFF_GUARD_THRESHOLD", "0.5"))
MAX_SOURCE_CHARS = 12_000
MARKER = "PROVENANCE_GUARD"

QUESTION = ("Every dollar figure and percentage in the ASSISTANT REPLY appears in, or is "
            "directly derived from, the SOURCE DATA.")

# Keyed by turn, cleared when the reply is checked.
_sources: dict[str, list] = {}


def _turn_key(kwargs: dict) -> str:
    return str(kwargs.get("turn_id") or kwargs.get("session_id") or "unknown")


def _key() -> str:
    return (os.environ.get("TYPESAFE_API_KEY") or "").strip()


def _cache_tool_result(tool_name: str, result, **kwargs):
    """Remember this turn's tool results. Always returns None: never transforms a result."""
    try:
        if not isinstance(result, str):
            try:
                result = json.dumps(result, default=str)
            except Exception:  # noqa: BLE001
                result = str(result)
        _sources.setdefault(_turn_key(kwargs), []).append(
            {"tool": tool_name, "result": result[:MAX_SOURCE_CHARS]})
        # Do not let a long session leak memory.
        if len(_sources) > 64:
            for k in list(_sources)[:-32]:
                _sources.pop(k, None)
    except Exception:  # noqa: BLE001
        logger.exception("provenance_guard: failed to cache %s", tool_name)
    return None


def _judge(reply: str, source_blob: str) -> float:
    body = {"state": f"SOURCE DATA:\n{source_blob}\n\nASSISTANT REPLY:\n{reply}",
            "model": MODEL,
            "questions": {"clean": {"type": "noul", "instructions": QUESTION,
                                    "criteria": {"true": "every figure traces to the source data",
                                                 "false": "at least one figure does not appear in the source data"}}}}
    req = urllib.request.Request(
        TYPESAFE_URL, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {_key()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.loads(r.read())
    return float(d["answers"]["clean"]["noul"])


def _check_reply(response_text: str, **kwargs):
    """MEASURE ONLY — always returns None, so the reply is never altered."""
    try:
        key = _turn_key(kwargs)
        sources = _sources.pop(key, [])
        source_blob = "\n".join(s["result"] for s in sources)

        # Nothing to check against, or nothing to check: record and leave the reply alone.
        figures = re.findall(r"\$[\d][\d,.]*|\b\d+(?:\.\d+)?%", response_text or "")
        record = {"ts": time.time(), "turn_id": kwargs.get("turn_id"),
                  "session_id": kwargs.get("session_id"), "model": kwargs.get("model"),
                  "tools": [s["tool"] for s in sources],
                  "source_chars": len(source_blob), "figures_in_reply": len(figures)}

        if not _key():
            record["skipped"] = "no TYPESAFE_API_KEY"
        elif not source_blob:
            record["skipped"] = "no tool results this turn"
        elif not figures:
            record["skipped"] = "no figures in reply"
        else:
            t0 = time.time()
            try:
                noul = _judge(response_text, source_blob)
                record.update(noul=round(noul, 4), suspect=noul < THRESHOLD,
                              judge_seconds=round(time.time() - t0, 2))
            except Exception as e:  # noqa: BLE001
                record.update(error=f"{type(e).__name__}: {str(e)[:160]}")

        # One line to stdout so the Railway logs carry it, plus a JSONL on the harness's own disk.
        logger.warning("%s %s", MARKER, json.dumps(record))
        try:
            os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception:  # noqa: BLE001
            pass
    except Exception:  # noqa: BLE001 — an observer must never break a turn
        logger.exception("provenance_guard: check failed")
    return None  # MEASURE-ONLY: never alters the reply


def register_provenance_guard(ctx) -> None:
    try:
        ctx.register_hook("transform_tool_result", _cache_tool_result)
        ctx.register_hook("transform_llm_output", _check_reply)
        logger.info("provenance_guard: measure-only, threshold %.2f, key %s",
                    THRESHOLD, "present" if _key() else "MISSING")
    except Exception:  # noqa: BLE001
        logger.exception("provenance_guard: could not register hooks")
