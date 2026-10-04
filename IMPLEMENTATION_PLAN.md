# Implementation Plan: Cloud-Cost-Optimizer

## 🎯 Objective
Build an end-to-end tool that identifies cloud waste using AI and automates the cost-reduction process.

## 📅 Phases

### Phase 1: The Data Collection Layer
- [x] Setup project structure.
- [x] Build Mock Data Generator (for testing).
- [x] Implement AWS Resource Collector using `boto3` (covered by fake-client tests; not yet run against a live account).
- [x] Normalize data into standardized JSON.

### Phase 2: The Intelligence Layer
- [ ] Design FinOps expert system prompts.
- [ ] Integrate LLM API (OpenAI/Claude).
- [ ] Implement structured JSON output for recommendations.

### Phase 3: The Action Layer
- [ ] Build "Dry Run" generator (Terraform/Bash).
- [ ] Implement SDK-based resource modification.
- [ ] Add safety guardrails and tagging filters.

### Phase 4: The Presentation Layer
- [ ] Develop Streamlit Dashboard.
- [ ] Implement Cost-Saving visualizer.
- [ ] Containerize with Docker.
- [ ] Setup CI/CD via GitHub Actions.
