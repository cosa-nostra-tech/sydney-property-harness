"""Log every tool result the model sees, so reply claims can be checked against sources.

WHY THIS EXISTS
The fabrication guard needs to answer one question: "is this figure actually in the data
this turn retrieved?" Calibrating that guard needs both sides of the pair — the reply AND
the source. The benchmark stored only replies, so the guard's false-positive rate was
unmeasurable, and an unmeasurable guard is one we cannot ship: a false positive blunts a
good answer, which costs the user confidence for no gain.

This hook is a pure OBSERVER. It returns None, so the result the model sees is byte-for-byte
what it would have been without the plugin. Nothing here can change a reply, slow a turn
in any way the user notices, or leak into output.

Written as JSONL, one line per tool result, with a wall-clock timestamp so the benchmark can
pair each reply with the tool results that produced it (questions run sequentially, so
"sources newer than when this question was sent" is the correct pairing).

Location is under /data because /tmp does not survive a container restart.
"""
from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

LOG_PATH = os.environ.get("TRIGGERBOFF_SOURCE_LOG", "/data/.hermes/tool_sources.jsonl")

# Results can be large (suburb pages, sale histories). Keep enough to verify any figure the
# reply could quote without letting one tool response dominate the file.
MAX_RESULT_CHARS = 20_000


def _log_tool_result(tool_name: str, args: dict, result, task_id: str = "", **kwargs):
    """Append one tool result to the source log. Always returns None: never transforms."""
    try:
        if not isinstance(result, str):
            try:
                result = json.dumps(result, default=str)
            except Exception:  # noqa: BLE001
                result = str(result)

        entry = {
            "ts": time.time(),
            "session_id": kwargs.get("session_id"),
            "turn_id": kwargs.get("turn_id"),
            "tool_call_id": kwargs.get("tool_call_id"),
            "tool": tool_name,
            "args": args if isinstance(args, (dict, list)) else str(args),
            "status": kwargs.get("status"),
            "result": result[:MAX_RESULT_CHARS],
            "result_truncated": len(result) > MAX_RESULT_CHARS,
        }

        os.makedirs(os.path.dirname(LOG_PATH) or ".", exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, default=str) + "\n")
    except Exception:  # noqa: BLE001 — an observer must never break a turn
        logger.exception("source_log: failed to record %s", tool_name)
    return None


def register_source_log(ctx) -> None:
    """Wire the observer into the plugin context."""
    try:
        ctx.register_hook("transform_tool_result", _log_tool_result)
        logger.info("source_log: recording tool results to %s", LOG_PATH)
    except Exception:  # noqa: BLE001
        logger.exception("source_log: could not register hook")
