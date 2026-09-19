# Sydney Property Buyer Harness

An AI assistant for buying property in Sydney, Australia. Built on [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research.

## What it does

- Answers questions about the NSW property buying process in plain language
- Calculates full upfront costs (deposit + stamp duty + LMI + legal + inspections)
- Checks First Home Buyer scheme eligibility (FHOG, FHBAS, First Home Guarantee, Help to Buy)
- Explains NSW-specific concepts: Section 66W, cooling-off, Section 10.7 certificates, exchange
- Searches Domain.com.au listings with context (days on market, underquoting flags)
- Provides suburb statistics and market context
- Flags Sydney-specific traps: underquoting, flight paths, flood zones, strata defects, contamination

## Deploy on Railway

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/template/deploy)

### Required environment variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | From BotFather — create a bot via @BotFather on Telegram |
| `OPENROUTER_API_KEY` | LLM provider — get at openrouter.ai |
| `HERMES_HOME` | Set to `/data/.hermes` |
| `ADMIN_PASSWORD` | Password for the web admin dashboard |
| `DOMAIN_API_KEY` | From developer.domain.com.au — free tier available |

### Optional

| Variable | Description |
|---|---|
| `LLM_MODEL` | Override model, default `anthropic/claude-sonnet-4.6` |
| `HERMES_REF` | Pin a specific Hermes version tag |

## Architecture

```
hermes-agent-template fork
├── docker/SOUL.md          ← Sydney property identity (baked into image, copied to volume on boot)
├── tools/
│   └── domain_property_tool.py  ← Domain API: search_properties, get_suburb_stats, get_property_details
├── start.sh                ← Modified to bootstrap SOUL.md and tools on every boot
└── Dockerfile              ← Modified to COPY docker/ and tools/ dirs
```

The SOUL.md is copied from the Docker image to `/data/.hermes/SOUL.md` on every boot via `start.sh`. This means it **survives redeploys** — unlike the standard approach of writing to the volume post-deploy.

The Domain API tool is registered with Hermes' tool registry on startup, making `search_properties`, `get_suburb_stats`, and `get_property_details` available to the agent.

## Getting a Domain API key

1. Go to [developer.domain.com.au](https://developer.domain.com.au)
2. Create a free account
3. Create an application — select "Listings" and "Suburb Performance" APIs
4. Copy your API key
5. Add as `DOMAIN_API_KEY` in Railway Variables

The free tier supports 500 requests/day which is sufficient for testing.

## Forking for other verticals

This repo demonstrates the pattern for building a vertical Hermes harness:

1. Fork `praveen-ks-2001/hermes-agent-template`
2. Replace `docker/SOUL.md` with your vertical's identity
3. Add custom tools in `tools/` (follow the `domain_property_tool.py` pattern)
4. Modify `start.sh` to copy SOUL.md and tools on boot
5. Add `COPY docker/ /app/docker/` and `COPY tools/ /app/tools/` to Dockerfile
6. Deploy on Railway

## Knowledge base

The full Sydney property corpus is documented at:
[Sydney Property Buyer OS — Complete Corpus](https://docs.google.com/document/d/1C3V6r3JPaB76Qf5-HIhuLL75AIsIGhUmbGSNqutcQMs/edit)

## Built by

[Atelier](https://atelier.co) — supply chain and AI infrastructure for consumer brands.
