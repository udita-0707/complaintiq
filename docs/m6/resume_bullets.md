# Résumé bullets (SPEC C15)

Owner: P3 (Udita). Measured numbers only, each with its split. Do not claim a public deployment:
there is none (reports/m5/deployment.md).

- Built an end-to-end NLP triage system on 1,253,594 CFPB complaint narratives, classifying 10
  products and 34 issues with a time-based split; product macro-F1 0.701 and issue top-3 accuracy
  0.845 on a test set read once after the model freeze.
- Designed a calibrated confidence gate (temperature scaling, product ECE 0.0540 to 0.0149 on
  held-out validation) that auto-routes 72.6% of test complaints at 93.6% precision and sends the
  rest to human review with a stated reason.
- Shipped a FastAPI service with PII scrubbing before inference, a text-free audit log, timeout
  and fallback handling and Prometheus metrics; single-request p95 latency 11.51 ms on CPU.
- Containerized it with Docker (local p95 82.6 ms at 10 concurrent clients, zero errors, 16 of 16
  failure tests passed) and built drift monitoring that replays production months against the
  training reference.
- Ran a 240-error manual error analysis showing that label ambiguity and taxonomy mismatch explain
  0.617 of issue errors, steering work toward label review rather than larger models.
