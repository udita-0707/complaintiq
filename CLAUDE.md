# ComplaintIQ

NLP Industry Track project: CFPB complaint triage (product/issue classification,
priority flag, routing, confidence-based human fallback, FastAPI service).
Source of truth: docs/SPEC.md. Follow it; do not add scope beyond it.

## Rules
- Python 3.11, src/complaintiq/ layout as in SPEC.md section C3.
- Config in configs/*.yaml, never hardcoded. Fixed seeds everywhere.
- Never use outcome fields (company response, timely response) as model inputs.
- Never log raw complaint text.
- Small, focused changes. Type hints and docstrings.
- Do not commit data/, models/, or secrets. Ask before adding dependencies.
