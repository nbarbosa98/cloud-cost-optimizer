"""Validates Claude's recommendations against the snapshot and prices the savings."""

from __future__ import annotations

from typing import Any

from collector import pricing
from collector.schema import COMPUTE, DATABASE, VOLUME, Resource, Snapshot

REPORT_VERSION = "1"

CATALOGUE = {
    COMPUTE: pricing.EC2_HOURLY,
    VOLUME: pricing.EBS_GB_MONTH,
    DATABASE: pricing.RDS_HOURLY,
}


def _cost(resource: Resource, size: str, running: bool) -> float | None:
    if resource.type == COMPUTE:
        return pricing.instance_monthly(size, running)
    if resource.type == VOLUME:
        return pricing.volume_monthly(size, resource.attributes["size_gb"])
    return pricing.database_monthly(
        size, resource.attributes["storage_gb"], resource.attributes["multi_az"], running
    )


def monthly_saving(resource: Resource, action: str, target_size: str | None) -> float | None:
    """Saving for one recommendation, or None if a price is unknown.

    Raises ValueError when the action cannot apply to the resource.
    """
    running = resource.state != "stopped"
    if action == "keep":
        return 0.0
    if action == "resize":
        if not target_size:
            raise ValueError("resize needs a target_size")
        if target_size == resource.size:
            raise ValueError("target_size is the current size")
        if target_size not in CATALOGUE[resource.type]:
            raise ValueError(f"unknown target size {target_size!r} for {resource.type}")
        after = _cost(resource, target_size, running)
    elif action == "stop":
        if resource.type == VOLUME:
            raise ValueError("volumes cannot be stopped")
        if not running:
            raise ValueError("already stopped")
        after = _cost(resource, resource.size, running=False)
    elif action == "delete":
        after = 0.0
    else:
        raise ValueError(f"unknown action {action!r}")

    if resource.monthly_cost_usd is None or after is None:
        return None
    return round(resource.monthly_cost_usd - after, 2)


def build_report(snapshot: Snapshot, raw: list[dict[str, Any]], model: str) -> dict[str, Any]:
    by_id = {r.id: r for r in snapshot.resources}
    recommendations: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for item in raw:
        resource_id, action = item["resource_id"], item["action"]
        resource = by_id.get(resource_id)
        try:
            if resource is None:
                raise ValueError("resource is not in the snapshot")
            if any(r["resource_id"] == resource_id for r in recommendations):
                raise ValueError("duplicate recommendation")
            saving = monthly_saving(resource, action, item.get("target_size"))
        except ValueError as error:
            rejected.append({"resource_id": resource_id, "action": action, "reason": str(error)})
            continue
        recommendations.append(
            {
                "resource_id": resource_id,
                "resource_type": resource.type,
                "name": resource.name,
                "action": action,
                "current_size": resource.size,
                "target_size": item["target_size"] if action == "resize" else None,
                "current_monthly_cost_usd": resource.monthly_cost_usd,
                "monthly_saving_usd": saving,
                "confidence": item["confidence"],
                "reasoning": item["reasoning"],
            }
        )

    # Largest savings first; unknown savings last.
    recommendations.sort(key=lambda r: (r["monthly_saving_usd"] is None, -(r["monthly_saving_usd"] or 0)))
    reviewed = {r["resource_id"] for r in recommendations}
    return {
        "report_version": REPORT_VERSION,
        "model": model,
        "source": snapshot.source,
        "snapshot_collected_at": snapshot.collected_at,
        "total_monthly_cost_usd": round(sum(r.monthly_cost_usd or 0 for r in snapshot.resources), 2),
        "total_monthly_saving_usd": round(sum(r["monthly_saving_usd"] or 0 for r in recommendations), 2),
        "recommendations": recommendations,
        "rejected": rejected,
        "unreviewed": sorted(set(by_id) - reviewed),
    }
