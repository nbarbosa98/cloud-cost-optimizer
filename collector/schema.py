"""Provider-agnostic resource schema shared by the collectors, analyst and UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = "1"

COMPUTE = "compute_instance"
VOLUME = "block_volume"
DATABASE = "database"
RESOURCE_TYPES = (COMPUTE, VOLUME, DATABASE)

STATES = ("running", "stopped", "attached", "unattached", "other")


@dataclass
class Resource:
    id: str
    provider: str
    type: str
    region: str
    size: str  # instance type, volume type or DB instance class
    state: str
    name: str | None = None
    created_at: str | None = None
    tags: dict[str, str] = field(default_factory=dict)
    monthly_cost_usd: float | None = None  # list-price estimate, None if unknown
    metrics: dict[str, float | None] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.type not in RESOURCE_TYPES:
            raise ValueError(f"Unknown resource type: {self.type!r}")
        if self.state not in STATES:
            raise ValueError(f"Unknown resource state: {self.state!r}")


@dataclass
class Snapshot:
    source: str
    lookback_days: int
    resources: list[Resource]
    collected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Snapshot:
        if data.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"Unsupported schema version: {data.get('schema_version')!r}")
        return cls(
            source=data["source"],
            lookback_days=data["lookback_days"],
            resources=[Resource(**r) for r in data["resources"]],
            collected_at=data["collected_at"],
        )
