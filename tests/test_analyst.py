import json
from types import SimpleNamespace

import pytest

import analyst.__main__ as cli
from analyst.llm import MODEL, OUTPUT_SCHEMA, AnalystError, recommend
from analyst.report import build_report, monthly_saving
from collector.schema import COMPUTE, DATABASE, VOLUME, Resource, Snapshot

INSTANCE = Resource(
    id="i-web", provider="aws", type=COMPUTE, region="us-east-1", size="t3.large", state="running",
    monthly_cost_usd=60.74, metrics={"cpu_avg_pct": 3.0, "cpu_max_pct": 12.0},
)
ORPHAN = Resource(
    id="vol-orphan", provider="aws", type=VOLUME, region="us-east-1", size="gp3", state="unattached",
    monthly_cost_usd=8.0, attributes={"size_gb": 100},
)
DB = Resource(
    id="orders-db", provider="aws", type=DATABASE, region="us-east-1", size="db.t3.medium", state="running",
    monthly_cost_usd=110.78, attributes={"storage_gb": 50, "multi_az": True},
)
UNPRICED = Resource(
    id="i-exotic", provider="aws", type=COMPUTE, region="us-east-1", size="x99.mega", state="running",
)
SNAPSHOT = Snapshot(source="mock", lookback_days=14, resources=[INSTANCE, ORPHAN, DB, UNPRICED])


def rec(resource_id, action, target_size=None):
    return {
        "resource_id": resource_id,
        "action": action,
        "target_size": target_size,
        "confidence": "high",
        "reasoning": "because",
    }


def fake_client(message):
    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            return message

    class Messages:
        def stream(self, **kwargs):
            self.kwargs = kwargs
            return Stream()

    return SimpleNamespace(beta=SimpleNamespace(messages=Messages()))


def test_savings_are_priced_from_the_table():
    assert monthly_saving(INSTANCE, "resize", "t3.small") == pytest.approx(45.56)
    assert monthly_saving(INSTANCE, "stop", None) == pytest.approx(60.74)
    assert monthly_saving(ORPHAN, "delete", None) == pytest.approx(8.0)
    # A stopped Multi-AZ database still pays for both copies of its storage.
    assert monthly_saving(DB, "stop", None) == pytest.approx(99.28)
    assert monthly_saving(DB, "keep", None) == 0.0
    assert monthly_saving(UNPRICED, "delete", None) is None


@pytest.mark.parametrize(
    "resource, action, target, reason",
    [
        (INSTANCE, "resize", None, "needs a target_size"),
        (INSTANCE, "resize", "t3.large", "current size"),
        (INSTANCE, "resize", "db.t3.micro", "unknown target size"),
        (ORPHAN, "stop", None, "cannot be stopped"),
        (INSTANCE, "terminate", None, "unknown action"),
    ],
)
def test_inapplicable_actions_are_rejected(resource, action, target, reason):
    with pytest.raises(ValueError, match=reason):
        monthly_saving(resource, action, target)


def test_report_keeps_valid_recommendations_and_explains_the_rest():
    raw = [
        rec("vol-orphan", "delete"),
        rec("i-web", "resize", "t3.small"),
        rec("i-web", "stop"),
        rec("i-ghost", "delete"),
        rec("orders-db", "keep", "db.t3.micro"),
    ]
    report = build_report(SNAPSHOT, raw, MODEL)

    assert [r["resource_id"] for r in report["recommendations"]] == ["i-web", "vol-orphan", "orders-db"]
    assert report["recommendations"][0]["monthly_saving_usd"] == pytest.approx(45.56)
    assert report["recommendations"][2]["target_size"] is None
    assert report["total_monthly_saving_usd"] == pytest.approx(53.56)
    assert report["total_monthly_cost_usd"] == pytest.approx(179.52)
    assert {(r["resource_id"], r["reason"]) for r in report["rejected"]} == {
        ("i-web", "duplicate recommendation"),
        ("i-ghost", "resource is not in the snapshot"),
    }
    assert report["unreviewed"] == ["i-exotic"]


def test_recommend_sends_snapshot_and_parses_structured_output():
    raw = [rec("i-web", "keep")]
    message = SimpleNamespace(
        stop_reason="end_turn",
        model=MODEL,
        content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text=json.dumps({"recommendations": raw})),
        ],
    )
    client = fake_client(message)

    assert recommend(SNAPSHOT, client=client) == (raw, MODEL)

    sent = client.beta.messages.kwargs
    assert sent["model"] == MODEL
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": OUTPUT_SCHEMA}
    assert "t3.small" in sent["system"][0]["text"]
    resources = json.loads(sent["messages"][0]["content"])["resources"]
    assert [r["id"] for r in resources] == ["i-web", "vol-orphan", "orders-db", "i-exotic"]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_recommend_raises_when_there_is_no_complete_answer(stop_reason):
    message = SimpleNamespace(stop_reason=stop_reason, model=MODEL, content=[])
    with pytest.raises(AnalystError):
        recommend(SNAPSHOT, client=fake_client(message))


def test_cli_writes_report(tmp_path, monkeypatch):
    snapshot_file = tmp_path / "snapshot.json"
    snapshot_file.write_text(json.dumps(SNAPSHOT.to_dict()))
    out = tmp_path / "recommendations.json"
    monkeypatch.setattr(cli, "recommend", lambda snapshot: ([rec("vol-orphan", "delete")], MODEL))

    assert cli.main([str(snapshot_file), "--out", str(out)]) == 0

    report = json.loads(out.read_text())
    assert report["total_monthly_saving_usd"] == pytest.approx(8.0)
    assert report["unreviewed"] == ["i-exotic", "i-web", "orders-db"]
