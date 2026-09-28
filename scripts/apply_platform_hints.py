#!/usr/bin/env python3
"""Replace the API-server platform hint so the web app is not told to write plain text.

THE PROBLEM
-----------
Hermes gives every platform a hint describing its rendering layer, and the queue for
`api_server` assumes the caller is unknown:

    "You're responding through an API server. The rendering layer is unknown — assume
     plain text. No markdown formatting (no asterisks, bullets, headers, code fences).
     Treat this like a conversation, not a document. Keep responses brief and natural."

That is the right default for an OpenAI-compatible endpoint, because the caller could
be a script or a client with no renderer. It is exactly wrong for THIS caller: the
TriggerBOFF web app renders full Markdown (components/ChatMarkdown.tsx), GFM tables and
inline charts.

The consequence was visible in the product. Same harness, same model, same 42-tool
toolset as Telegram — but Telegram is told "lean into real Markdown tables, bullet and
numbered lists, headings, blockquotes" while the web app is told to use no bullets, no
headers, no tables, and to keep it brief. Measured against the same golden questions,
that is the difference between an answer that reads well and one that does not.

THE FIX
-------
Hermes reads a config override at agent init:

    agent._platform_hint_overrides = _cfg_dict(cfg, "platform_hints")   # top level
    # agent/system_prompt.py::_resolve_platform_hint()
    #   spec = {"replace": str} or {"append": str}; a bare string means append

So setting `platform_hints.api_server.replace` swaps the default for a hint that
describes what the app can actually render. Config only — no Hermes code, no app code.

Written to the config on every boot by start.sh, the same way SOUL.md is, so it
survives redeploys and cannot drift from the repo.

Safety: if the config already carries a top-level `platform_hints` key this refuses and
exits non-zero rather than doing a YAML round-trip that would strip the 112KB of
documentation comments from the example config.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

CONFIG = Path("/data/.hermes/config.yaml")

HINT = """You're responding through the TriggerBOFF web app, which renders full Markdown.

Answer in the first sentence, then support it. Be succinct — 400-700 words, nothing that
does not change a decision.

Use ## headings for structure, bullets for lists, Markdown tables for figures side by
side, and a fenced `chart` block where a comparison or trend is the point.

Credibility rules: every figure you state must be one you actually obtained or one you
clearly label as an estimate. Never present an estimate as a settled figure. Give the
date or basis for market numbers in a few words. Give one recommendation and the single
strongest reason for it, rather than listing every consideration.

Never mention tools, data sources or anything being unavailable."""

BLOCK = f"""# ── platform_hints ────────────────────────────────────────────────────────────
# Managed by scripts/apply_platform_hints.py, applied on every boot by start.sh.
# The built-in `api_server` hint tells the model to assume plain text and use no
# Markdown, which inverts what the TriggerBOFF web app can render. Replaced here.
# See the script for the full reasoning.
platform_hints:
  api_server:
    replace: |
{chr(10).join('      ' + line if line else '' for line in HINT.splitlines())}
"""


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else CONFIG
    if not target.exists():
        print(f"apply_platform_hints: {target} not found", file=sys.stderr)
        return 1

    text = target.read_text(encoding="utf-8")

    # Idempotency FIRST. start.sh runs this on every boot, so the second boot must be a
    # clean no-op — and must exit 0. Checking the "already present" guard below first
    # would make boot 2 exit non-zero, which under `set -e` aborts the container start.
    if "TriggerBOFF web app" in text and re.search(r"(?m)^platform_hints\s*:", text):
        print("apply_platform_hints: already applied, nothing to do")
        return 0

    # Top-level key check. A non-zero indent means it belongs to a nested mapping.
    if re.search(r"(?m)^platform_hints\s*:", text):
        print("apply_platform_hints: refusing to edit — top-level platform_hints "
              "already present from another source (a YAML round-trip would strip the "
              "example comments)", file=sys.stderr)
        return 1

    # Requires a trailing newline so the appended key is not glued to the last line.
    if not text.endswith("\n"):
        text += "\n"
    target.write_text(text + "\n" + BLOCK, encoding="utf-8")
    print(f"apply_platform_hints: replaced api_server hint in {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
