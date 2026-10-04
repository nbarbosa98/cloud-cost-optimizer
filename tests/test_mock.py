import json
from datetime import datetime, timezone

from collector import mock
from collector.__main__ import main
from collector.schema import RESOURCE_TYPES, Snapshot

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_same_seed_is_deterministic():
    assert mock.generate(seed=7, now=NOW).resources == mock.generate(seed=7, now=NOW).resources
    assert mock.generate(seed=7, now=NOW).resources != mock.generate(seed=8, now=NOW).resources


def test_generates_requested_mix():
    snapshot = mock.generate(count=200, seed=1, now=NOW)
    assert len(snapshot.resources) == 200
    assert {r.type for r in snapshot.resources} == set(RESOURCE_TYPES)
    assert {"running", "stopped", "attached", "unattached"} <= {r.state for r in snapshot.resources}
    assert all(r.monthly_cost_usd is not None for r in snapshot.resources)
    assert len({r.id for r in snapshot.resources}) == 200


def test_snapshot_round_trips_through_json():
    snapshot = mock.generate(count=20, now=NOW)
    assert Snapshot.from_dict(json.loads(json.dumps(snapshot.to_dict()))) == snapshot


def test_cli_writes_snapshot_file(tmp_path):
    out = tmp_path / "snapshot.json"
    assert main(["--count", "5", "--out", str(out)]) == 0
    snapshot = Snapshot.from_dict(json.loads(out.read_text()))
    assert snapshot.source == "mock"
    assert len(snapshot.resources) == 5
