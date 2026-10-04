"""Claude call: turns a snapshot into one schema-enforced recommendation per resource."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import anthropic

from collector import pricing
from collector.schema import Snapshot

MODEL = "claude-opus-5-5"

ACTIONS = ("resize", "stop", "delete", "keep")

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "recommendations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "resource_id": {"type": "string"},
                    "action": {"type": "string", "enum": list(ACTIONS)},
                    "target_size": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
                    "reasoning": {"type": "string"},
                },
                "required": ["resource_id", "action", "target_size", "confidence", "reasoning"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["recommendations"],
    "additionalProperties": False,
}


def _catalogue(title: str, prices: dict[str, float], unit: str) -> str:
    return f"{title}:\n" + "\n".join(f"- {size}: ${price} {unit}" for size, price in prices.items())


SYSTEM_PROMPT = f"""You are a FinOps analyst reviewing a snapshot of cloud resources to find waste. \
Your recommendations go to an engineer who decides whether to act, and later to an automation \
step that can apply them, so a wrong "delete" costs far more than a missed saving. Recommend a \
change only when the evidence in the snapshot supports it.

The snapshot is JSON. Each resource has a type (compute_instance, block_volume or database), a \
size, a state, tags, an estimated monthly cost and usage metrics measured over lookback_days:
- cpu_avg_pct / cpu_max_pct: average and peak CPU utilisation.
- connections_avg / connections_max: database connections.
- read_ops / write_ops: total volume I/O operations over the window.
A metric that is null or missing means there was no data, not zero usage. Treat it as unknown and \
lower your confidence.

Return exactly one recommendation for every resource, using its id as resource_id. Actions:
- resize: move to a different size. Set target_size to a size from the catalogue below, for the \
same resource type. Size for the peak, not the average: the new size should leave headroom over \
cpu_max_pct, remembering that halving capacity roughly doubles utilisation.
- stop: stop a running instance or database that looks idle but may be needed again. Not valid \
for volumes.
- delete: remove a resource nothing appears to use, such as an unattached volume or an instance \
that has been stopped for a long time.
- keep: the resource is reasonably sized or there is not enough evidence to change it.
Set target_size to null for every action except resize.

Use tags as context. Production resources deserve more caution than dev or staging ones, and \
when two actions are plausible prefer the one that is easier to undo (resize or stop over delete).

Do not estimate savings. They are calculated from the price table after you respond. Keep \
reasoning to one or two sentences that cite the numbers you relied on.

Size catalogue (approximate on-demand list prices):
{_catalogue("Compute instances", pricing.EC2_HOURLY, "per hour")}
{_catalogue("Databases", pricing.RDS_HOURLY, "per hour")}
{_catalogue("Volumes", pricing.EBS_GB_MONTH, "per GB-month")}
"""


class AnalystError(RuntimeError):
    pass


def recommend(snapshot: Snapshot, client: Any = None) -> tuple[list[dict[str, Any]], str]:
    """Return the raw recommendations and the model that produced them."""
    client = client or anthropic.Anthropic()
    payload = {
        "lookback_days": snapshot.lookback_days,
        "resources": [asdict(r) for r in snapshot.resources],
    }
    # Streamed so a large snapshot cannot hit the HTTP timeout. Fallbacks re-run the
    # request on another model if a safety classifier declines it.
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=64000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
        messages=[{"role": "user", "content": json.dumps(payload, sort_keys=True)}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise AnalystError("Claude declined to analyse this snapshot")
    if message.stop_reason == "max_tokens":
        raise AnalystError("Response was cut off at max_tokens; analyse a smaller snapshot")
    text = next(block.text for block in message.content if block.type == "text")
    return json.loads(text)["recommendations"], message.model
