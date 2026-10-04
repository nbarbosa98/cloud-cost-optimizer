from datetime import datetime, timezone

import pytest

from collector import aws
from collector.schema import COMPUTE, DATABASE, VOLUME

LAUNCHED = datetime(2025, 6, 1, 12, 0, tzinfo=timezone.utc)

RUNNING = {
    "InstanceId": "i-running",
    "InstanceType": "t3.large",
    "State": {"Name": "running"},
    "LaunchTime": LAUNCHED,
    "Tags": [{"Key": "Name", "Value": "web-01"}, {"Key": "env", "Value": "prod"}],
}
STOPPED = {"InstanceId": "i-stopped", "InstanceType": "m5.large", "State": {"Name": "stopped"}}
ATTACHED = {
    "VolumeId": "vol-attached",
    "VolumeType": "gp2",
    "Size": 50,
    "State": "in-use",
    "Attachments": [{"InstanceId": "i-running"}],
}
UNATTACHED = {"VolumeId": "vol-orphan", "VolumeType": "gp3", "Size": 100, "State": "available", "Attachments": []}
DB = {
    "DBInstanceIdentifier": "orders-db",
    "DBInstanceClass": "db.t3.medium",
    "Engine": "postgres",
    "DBInstanceStatus": "available",
    "AllocatedStorage": 50,
    "MultiAZ": True,
    "TagList": [{"Key": "team", "Value": "payments"}],
}


class FakePaginator:
    def __init__(self, pages):
        self.pages = pages

    def paginate(self, **kwargs):
        return iter(self.pages)


class FakeClient:
    def __init__(self, pages=None, datapoints=None):
        self.pages = pages or {}
        self.datapoints = datapoints or {}
        self.calls = []

    def get_paginator(self, operation):
        return FakePaginator(self.pages[operation])

    def get_metric_statistics(self, **kwargs):
        self.calls.append(kwargs)
        return {"Datapoints": self.datapoints.get(kwargs["MetricName"], [])}


class FakeSession:
    def __init__(self, clients, region_name="eu-west-1"):
        self.clients = clients
        self.region_name = region_name

    def client(self, name):
        return self.clients[name]


def test_normalize_instance():
    resource = aws.normalize_instance(RUNNING, "eu-west-1", {"cpu_avg_pct": 3.0})
    assert resource.type == COMPUTE
    assert resource.state == "running"
    assert resource.name == "web-01"
    assert resource.tags == {"Name": "web-01", "env": "prod"}
    assert resource.created_at == "2025-06-01T12:00:00+00:00"
    assert resource.monthly_cost_usd == pytest.approx(60.74)


def test_unknown_size_has_no_cost_estimate():
    raw = {**RUNNING, "InstanceType": "x99.mega"}
    assert aws.normalize_instance(raw, "eu-west-1", {}).monthly_cost_usd is None


def test_transitional_state_maps_to_other():
    raw = {**RUNNING, "State": {"Name": "stopping"}}
    resource = aws.normalize_instance(raw, "eu-west-1", {})
    assert resource.state == "other"
    assert resource.attributes["raw_state"] == "stopping"


def test_collect_normalizes_all_resource_types():
    cloudwatch = FakeClient(
        datapoints={
            "CPUUtilization": [{"Average": 2.0, "Maximum": 10.0}, {"Average": 4.0, "Maximum": 30.0}],
            "VolumeReadOps": [{"Sum": 100.0}, {"Sum": 50.0}],
            "VolumeWriteOps": [{"Sum": 10.0}],
            "DatabaseConnections": [{"Average": 0.0, "Maximum": 1.0}],
        }
    )
    session = FakeSession(
        {
            "ec2": FakeClient(
                pages={
                    "describe_instances": [{"Reservations": [{"Instances": [RUNNING, STOPPED]}]}],
                    "describe_volumes": [{"Volumes": [ATTACHED]}, {"Volumes": [UNATTACHED]}],
                }
            ),
            "rds": FakeClient(pages={"describe_db_instances": [{"DBInstances": [DB]}]}),
            "cloudwatch": cloudwatch,
        }
    )

    snapshot = aws.collect(lookback_days=14, session=session)
    by_id = {r.id: r for r in snapshot.resources}

    assert snapshot.source == "aws"
    assert len(by_id) == 5
    assert all(r.region == "eu-west-1" and r.provider == "aws" for r in snapshot.resources)

    assert by_id["i-running"].metrics == {"cpu_avg_pct": 3.0, "cpu_max_pct": 30.0}
    assert by_id["i-stopped"].state == "stopped"
    assert by_id["i-stopped"].metrics == {}
    assert by_id["i-stopped"].monthly_cost_usd == 0.0

    assert by_id["vol-attached"].type == VOLUME
    assert by_id["vol-attached"].state == "attached"
    assert by_id["vol-attached"].metrics == {"read_ops": 150.0, "write_ops": 10.0}
    assert by_id["vol-attached"].attributes["attached_to"] == ["i-running"]
    assert by_id["vol-orphan"].state == "unattached"
    assert by_id["vol-orphan"].metrics == {}
    assert by_id["vol-orphan"].monthly_cost_usd == pytest.approx(8.0)

    database = by_id["orders-db"]
    assert database.type == DATABASE
    assert database.state == "running"
    assert database.tags == {"team": "payments"}
    assert database.metrics == {
        "cpu_avg_pct": 3.0,
        "cpu_max_pct": 30.0,
        "connections_avg": 0.0,
        "connections_max": 1.0,
    }
    assert database.monthly_cost_usd == pytest.approx(110.78)

    # Stopped and unattached resources have no usage to query.
    queried = {call["Dimensions"][0]["Value"] for call in cloudwatch.calls}
    assert queried == {"i-running", "vol-attached", "orders-db"}
    assert all(call["Period"] == 3600 for call in cloudwatch.calls)


def test_collect_requires_a_region():
    with pytest.raises(ValueError, match="region"):
        aws.collect(session=FakeSession({}, region_name=None))
