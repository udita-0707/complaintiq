---
title: ComplaintIQ API
emoji: 🗂️
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
short_description: CFPB complaint triage API (product, issue, priority, routing)
---

# ComplaintIQ API

Triage API for consumer financial complaints: product and issue classification, a priority
flag, team routing, and a calibrated confidence gate that sends uncertain cases to human
review. Decision support only: a person handles every complaint, and the system never
triggers an adverse customer outcome.

- `POST /v1/triage` with `{"text": "..."}` (20 to 10,000 characters, English)
- `POST /v1/feedback` with a `request_id` and corrected labels
- `GET /health`, `GET /v1/model`, `GET /metrics` (Prometheus), `GET /docs`

Model: TF-IDF + linear classifiers trained on public CFPB complaints, frozen at milestone M4
(see `configs/final_model.yaml` in the source repository). Text is PII-scrubbed before
inference and never logged or stored. The request log on this free Space is reset when the
Space restarts.

Source: https://github.com/udita-0707/complaintiq
