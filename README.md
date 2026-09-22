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

---
*This project was built to showcase experience in Cloud Administration, LLMOps, and Infrastructure as Code.*
