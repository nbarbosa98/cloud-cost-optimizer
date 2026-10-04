# Cloud-Cost-Optimizer

Cloud-Cost-Optimizer is an AI-driven cloud financial management (FinOps) tool designed to identify underutilized resources and provide actionable cost-reduction recommendations.

## 🚀 Overview
The tool scans cloud infrastructure, analyzes utilization metrics via an LLM, and suggests optimized resource configurations to reduce monthly spending without sacrificing performance.

## 🛠️ Key Features
- **Resource Discovery:** Programmatically identifies active instances, volumes, and databases.
- **AI Analysis:** Leverages LLMs to translate raw metrics into financial optimization strategies.
- **Actionable Insights:** Provides specific recommendations (e.g., "Downsize i-123 from t3.large to t3.micro").
- **Automated Remediation:** Ability to generate Terraform plans or execute changes via SDK.

## 🏗️ Architecture
`Cloud Provider` $\rightarrow$ `Python Collector` $\rightarrow$ `LLM Analyst` $\rightarrow$ `Action Engine` $\rightarrow$ `Streamlit UI`

## 📂 Project Structure
- `/collector`: Data ingestion and normalization.
- `/analyst`: LLM prompt engineering and analysis.
- `/executor`: Automation and IaC generation.
- `/ui`: Streamlit dashboard.

## ⚡ Quick Start
```bash
pip install -e ".[dev]"

# Mock snapshot (no cloud credentials needed)
python -m collector --source mock --count 30 --seed 42 --out snapshot.json

# Real AWS snapshot (read-only: EC2, EBS, RDS and CloudWatch)
python -m collector --source aws --region eu-west-1 --lookback-days 14 --out snapshot.json

# Recommendations from Claude (needs ANTHROPIC_API_KEY)
python -m analyst snapshot.json --out recommendations.json

pytest
```

### Collector output
Both sources produce the same normalized JSON, defined in `collector/schema.py`:

```json
{
  "schema_version": "1",
  "source": "mock",
  "lookback_days": 14,
  "collected_at": "2026-10-04T10:00:00+00:00",
  "resources": [
    {
      "id": "i-0abc...",
      "provider": "aws",
      "type": "compute_instance",
      "region": "us-east-1",
      "size": "t3.large",
      "state": "running",
      "name": "web-prod-app-01",
      "created_at": "2025-06-01T12:00:00+00:00",
      "tags": {"env": "prod", "team": "web"},
      "monthly_cost_usd": 60.74,
      "metrics": {"cpu_avg_pct": 3.1, "cpu_max_pct": 12.4},
      "attributes": {"raw_state": "running"}
    }
  ]
}
```

`type` is one of `compute_instance`, `block_volume` or `database`. `monthly_cost_usd` is an estimate from approximate us-east-1 list prices (`collector/pricing.py`), not billing data, and is `null` for sizes outside that table.

The AWS collector needs `ec2:DescribeInstances`, `ec2:DescribeVolumes`, `rds:DescribeDBInstances` and `cloudwatch:GetMetricStatistics`.

### Analyst output
Claude (`claude-opus-5-5`) chooses one action per resource: `resize`, `stop`, `delete` or `keep`. The response is schema-enforced JSON. Claude does not produce any dollar figures: `analyst/report.py` checks each recommendation against the snapshot and computes the saving from the price table.

```json
{
  "report_version": "1",
  "model": "claude-opus-5-5",
  "total_monthly_cost_usd": 1830.12,
  "total_monthly_saving_usd": 412.5,
  "recommendations": [
    {
      "resource_id": "i-0abc...",
      "resource_type": "compute_instance",
      "name": "web-prod-app-01",
      "action": "resize",
      "current_size": "t3.large",
      "target_size": "t3.small",
      "current_monthly_cost_usd": 60.74,
      "monthly_saving_usd": 45.56,
      "confidence": "high",
      "reasoning": "CPU averaged 3.1% and peaked at 12.4% over 14 days."
    }
  ],
  "rejected": [],
  "unreviewed": []
}
```

- `rejected` lists recommendations that could not apply, such as an unknown resource id or a size outside the price table, with the reason.
- `unreviewed` lists resources Claude returned no usable recommendation for.
- `monthly_saving_usd` is `null` when the resource's size has no price.

---
*This project was built to showcase experience in Cloud Administration, LLMOps, and Infrastructure as Code.*
