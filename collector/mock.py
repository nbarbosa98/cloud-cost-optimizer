"""Mock data generator: seeded, AWS-shaped resources with a realistic mix of waste.

Records are built in the raw boto3 shape and passed through the same
normalizers as the real collector, so mock snapshots exercise the same path.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from .aws import normalize_database, normalize_instance, normalize_volume
from .pricing import EBS_GB_MONTH, EC2_HOURLY, RDS_HOURLY
from .schema import Snapshot

TEAMS = ["payments", "search", "platform", "analytics", "web"]
ENVS = ["prod", "staging", "dev"]
ENGINES = ["postgres", "mysql"]
VOLUME_SIZES_GB = [20, 50, 100, 250, 500, 1000]
DB_STORAGE_GB = [20, 50, 100, 200, 500]

# (profile, weight, state, cpu avg % range, cpu max % range)
INSTANCE_PROFILES = [
    ("idle", 3, "running", (1, 4), (5, 15)),
    ("oversized", 3, "running", (5, 15), (20, 40)),
    ("healthy", 3, "running", (35, 65), (70, 95)),
    ("stopped", 1, "stopped", None, None),
]

# (profile, weight, state, read/write ops range over the lookback window)
VOLUME_PROFILES = [
    ("active", 5, "in-use", (50_000, 5_000_000)),
    ("idle", 2, "in-use", (0, 0)),
    ("unattached", 3, "available", None),
]

# (profile, weight, status, cpu avg % range, cpu max % range, avg connections range)
DATABASE_PROFILES = [
    ("idle", 2, "available", (1, 3), (4, 10), (0, 0)),
    ("oversized", 3, "available", (4, 12), (15, 35), (2, 10)),
    ("healthy", 4, "available", (30, 60), (65, 90), (20, 150)),
    ("stopped", 1, "stopped", None, None, None),
]


def _pick(rng: random.Random, profiles: list[tuple]) -> tuple:
    return rng.choices(profiles, weights=[p[1] for p in profiles])[0]


def _hex_id(rng: random.Random, prefix: str) -> str:
    return f"{prefix}-{rng.getrandbits(68):017x}"


def _identity(rng: random.Random, role: str, n: int) -> tuple[str, list[dict[str, str]]]:
    team, env = rng.choice(TEAMS), rng.choice(ENVS)
    name = f"{team}-{env}-{role}-{n:02d}"
    tags = [{"Key": "Name", "Value": name}, {"Key": "env", "Value": env}, {"Key": "team", "Value": team}]
    return name, tags


def _created(rng: random.Random, now: datetime) -> datetime:
    return now - timedelta(days=rng.randint(20, 900))


def _span(rng: random.Random, bounds: tuple[float, float]) -> float:
    return round(rng.uniform(*bounds), 2)


def generate(
    count: int = 30,
    seed: int = 42,
    lookback_days: int = 14,
    region: str = "us-east-1",
    now: datetime | None = None,
) -> Snapshot:
    rng = random.Random(seed)
    now = now or datetime.now(timezone.utc)
    n_instances = round(count * 0.5)
    n_databases = round(count * 0.2)
    n_volumes = count - n_instances - n_databases

    resources = []
    instance_ids = []

    for n in range(n_instances):
        _, _, state, avg, peak = _pick(rng, INSTANCE_PROFILES)
        _, tags = _identity(rng, "app", n)
        raw = {
            "InstanceId": _hex_id(rng, "i"),
            "InstanceType": rng.choice(list(EC2_HOURLY)),
            "State": {"Name": state},
            "LaunchTime": _created(rng, now),
            "Tags": tags,
        }
        metrics = {"cpu_avg_pct": _span(rng, avg), "cpu_max_pct": _span(rng, peak)} if avg else {}
        instance_ids.append(raw["InstanceId"])
        resources.append(normalize_instance(raw, region, metrics))

    for n in range(n_volumes):
        _, _, state, ops = _pick(rng, VOLUME_PROFILES)
        _, tags = _identity(rng, "data", n)
        attachments = []
        if state == "in-use":
            attachments = [{"InstanceId": rng.choice(instance_ids) if instance_ids else _hex_id(rng, "i")}]
        raw = {
            "VolumeId": _hex_id(rng, "vol"),
            "VolumeType": rng.choice(list(EBS_GB_MONTH)),
            "Size": rng.choice(VOLUME_SIZES_GB),
            "State": state,
            "CreateTime": _created(rng, now),
            "Encrypted": rng.random() < 0.8,
            "Attachments": attachments,
            "Tags": tags,
        }
        metrics = {"read_ops": rng.randint(*ops), "write_ops": rng.randint(*ops)} if ops else {}
        resources.append(normalize_volume(raw, region, metrics))

    for n in range(n_databases):
        _, _, status, avg, peak, connections = _pick(rng, DATABASE_PROFILES)
        name, tags = _identity(rng, "db", n)
        raw = {
            "DBInstanceIdentifier": name,
            "DBInstanceClass": rng.choice(list(RDS_HOURLY)),
            "Engine": rng.choice(ENGINES),
            "DBInstanceStatus": status,
            "AllocatedStorage": rng.choice(DB_STORAGE_GB),
            "MultiAZ": rng.random() < 0.3,
            "InstanceCreateTime": _created(rng, now),
            "TagList": tags,
        }
        metrics = {}
        if avg:
            connections_avg = _span(rng, connections)
            metrics = {
                "cpu_avg_pct": _span(rng, avg),
                "cpu_max_pct": _span(rng, peak),
                "connections_avg": connections_avg,
                "connections_max": round(connections_avg * rng.uniform(1, 3)),
            }
        resources.append(normalize_database(raw, region, metrics))

    return Snapshot(source="mock", lookback_days=lookback_days, resources=resources)
