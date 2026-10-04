"""AWS collector: EC2 instances, EBS volumes and RDS databases with CloudWatch usage."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from . import pricing
from .schema import COMPUTE, DATABASE, VOLUME, Resource, Snapshot

INSTANCE_STATES = {"running": "running", "stopped": "stopped"}
VOLUME_STATES = {"in-use": "attached", "available": "unattached"}
DATABASE_STATES = {"available": "running", "stopped": "stopped"}


def _tags(raw: list[dict[str, str]] | None) -> dict[str, str]:
    return {t["Key"]: t["Value"] for t in raw or []}


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def normalize_instance(raw: dict[str, Any], region: str, metrics: dict[str, float | None]) -> Resource:
    tags = _tags(raw.get("Tags"))
    state = INSTANCE_STATES.get(raw["State"]["Name"], "other")
    return Resource(
        id=raw["InstanceId"],
        provider="aws",
        type=COMPUTE,
        region=region,
        size=raw["InstanceType"],
        state=state,
        name=tags.get("Name"),
        created_at=_iso(raw.get("LaunchTime")),
        tags=tags,
        monthly_cost_usd=pricing.instance_monthly(raw["InstanceType"], running=state != "stopped"),
        metrics=metrics,
        attributes={"raw_state": raw["State"]["Name"]},
    )


def normalize_volume(raw: dict[str, Any], region: str, metrics: dict[str, float | None]) -> Resource:
    tags = _tags(raw.get("Tags"))
    return Resource(
        id=raw["VolumeId"],
        provider="aws",
        type=VOLUME,
        region=region,
        size=raw["VolumeType"],
        state=VOLUME_STATES.get(raw["State"], "other"),
        name=tags.get("Name"),
        created_at=_iso(raw.get("CreateTime")),
        tags=tags,
        monthly_cost_usd=pricing.volume_monthly(raw["VolumeType"], raw["Size"]),
        metrics=metrics,
        attributes={
            "raw_state": raw["State"],
            "size_gb": raw["Size"],
            "iops": raw.get("Iops"),
            "encrypted": raw.get("Encrypted"),
            "attached_to": [a["InstanceId"] for a in raw.get("Attachments", [])],
        },
    )


def normalize_database(raw: dict[str, Any], region: str, metrics: dict[str, float | None]) -> Resource:
    state = DATABASE_STATES.get(raw["DBInstanceStatus"], "other")
    multi_az = raw.get("MultiAZ", False)
    return Resource(
        id=raw["DBInstanceIdentifier"],
        provider="aws",
        type=DATABASE,
        region=region,
        size=raw["DBInstanceClass"],
        state=state,
        name=raw["DBInstanceIdentifier"],
        created_at=_iso(raw.get("InstanceCreateTime")),
        tags=_tags(raw.get("TagList")),
        monthly_cost_usd=pricing.database_monthly(
            raw["DBInstanceClass"], raw["AllocatedStorage"], multi_az, running=state != "stopped"
        ),
        metrics=metrics,
        attributes={
            "raw_state": raw["DBInstanceStatus"],
            "engine": raw.get("Engine"),
            "storage_gb": raw["AllocatedStorage"],
            "multi_az": multi_az,
        },
    )


def _avg_max(points: list[dict[str, Any]], avg_key: str, max_key: str) -> dict[str, float | None]:
    if not points:
        return {avg_key: None, max_key: None}
    return {
        avg_key: round(sum(p["Average"] for p in points) / len(points), 2),
        max_key: round(max(p["Maximum"] for p in points), 2),
    }


def _total(points: list[dict[str, Any]]) -> float:
    return sum(p["Sum"] for p in points)


def collect(region: str | None = None, lookback_days: int = 14, session: Any = None) -> Snapshot:
    if session is None:
        import boto3

        session = boto3.Session(region_name=region)
    region = session.region_name
    if not region:
        raise ValueError("No AWS region: pass --region or set AWS_DEFAULT_REGION")

    ec2 = session.client("ec2")
    rds = session.client("rds")
    cloudwatch = session.client("cloudwatch")

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days)
    # CloudWatch returns at most 1440 datapoints per call.
    period = 3600 if lookback_days <= 60 else 86400

    def datapoints(namespace: str, metric: str, dimension: str, value: str, statistics: list[str]):
        return cloudwatch.get_metric_statistics(
            Namespace=namespace,
            MetricName=metric,
            Dimensions=[{"Name": dimension, "Value": value}],
            StartTime=start,
            EndTime=end,
            Period=period,
            Statistics=statistics,
        )["Datapoints"]

    resources: list[Resource] = []

    live = [{"Name": "instance-state-name", "Values": ["pending", "running", "stopping", "stopped"]}]
    for page in ec2.get_paginator("describe_instances").paginate(Filters=live):
        for reservation in page["Reservations"]:
            for raw in reservation["Instances"]:
                metrics: dict[str, float | None] = {}
                if raw["State"]["Name"] == "running":
                    points = datapoints(
                        "AWS/EC2", "CPUUtilization", "InstanceId", raw["InstanceId"], ["Average", "Maximum"]
                    )
                    metrics = _avg_max(points, "cpu_avg_pct", "cpu_max_pct")
                resources.append(normalize_instance(raw, region, metrics))

    for page in ec2.get_paginator("describe_volumes").paginate():
        for raw in page["Volumes"]:
            metrics = {}
            if raw["State"] == "in-use":
                metrics = {
                    "read_ops": _total(datapoints("AWS/EBS", "VolumeReadOps", "VolumeId", raw["VolumeId"], ["Sum"])),
                    "write_ops": _total(datapoints("AWS/EBS", "VolumeWriteOps", "VolumeId", raw["VolumeId"], ["Sum"])),
                }
            resources.append(normalize_volume(raw, region, metrics))

    for page in rds.get_paginator("describe_db_instances").paginate():
        for raw in page["DBInstances"]:
            metrics = {}
            if raw["DBInstanceStatus"] == "available":
                db_id = raw["DBInstanceIdentifier"]
                stats = ["Average", "Maximum"]
                metrics = {
                    **_avg_max(
                        datapoints("AWS/RDS", "CPUUtilization", "DBInstanceIdentifier", db_id, stats),
                        "cpu_avg_pct",
                        "cpu_max_pct",
                    ),
                    **_avg_max(
                        datapoints("AWS/RDS", "DatabaseConnections", "DBInstanceIdentifier", db_id, stats),
                        "connections_avg",
                        "connections_max",
                    ),
                }
            resources.append(normalize_database(raw, region, metrics))

    return Snapshot(source="aws", lookback_days=lookback_days, resources=resources)
