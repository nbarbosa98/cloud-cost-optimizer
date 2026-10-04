"""Approximate us-east-1 on-demand list prices, used to estimate monthly cost.

Estimates only: they ignore region, discounts, reserved capacity and data
transfer. Sizes missing from the tables yield None rather than a guess.
"""

from __future__ import annotations

HOURS_PER_MONTH = 730

EC2_HOURLY = {
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
    "t3.medium": 0.0416,
    "t3.large": 0.0832,
    "t3.xlarge": 0.1664,
    "m5.large": 0.096,
    "m5.xlarge": 0.192,
    "m5.2xlarge": 0.384,
    "c5.large": 0.085,
    "c5.xlarge": 0.17,
    "r5.large": 0.126,
    "r5.xlarge": 0.252,
}

RDS_HOURLY = {
    "db.t3.micro": 0.017,
    "db.t3.small": 0.034,
    "db.t3.medium": 0.068,
    "db.m5.large": 0.171,
    "db.m5.xlarge": 0.342,
    "db.r5.large": 0.24,
}

EBS_GB_MONTH = {
    "gp3": 0.08,
    "gp2": 0.10,
    "io1": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
}

RDS_STORAGE_GB_MONTH = 0.115


def instance_monthly(instance_type: str, running: bool) -> float | None:
    # A stopped instance has no compute charge; its volumes are costed separately.
    if not running:
        return 0.0
    hourly = EC2_HOURLY.get(instance_type)
    return None if hourly is None else round(hourly * HOURS_PER_MONTH, 2)


def volume_monthly(volume_type: str, size_gb: int) -> float | None:
    rate = EBS_GB_MONTH.get(volume_type)
    return None if rate is None else round(rate * size_gb, 2)


def database_monthly(db_class: str, storage_gb: int, multi_az: bool, running: bool) -> float | None:
    copies = 2 if multi_az else 1
    storage = RDS_STORAGE_GB_MONTH * storage_gb
    # A stopped database still pays for its storage.
    if not running:
        return round(storage * copies, 2)
    hourly = RDS_HOURLY.get(db_class)
    return None if hourly is None else round((hourly * HOURS_PER_MONTH + storage) * copies, 2)
