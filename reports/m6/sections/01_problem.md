# Problem, users and scope

## Problem

Banks, lenders and fintechs receive large volumes of free-text complaints. Each must be
categorized, routed to the right team and answered within regulatory timelines. Manual or
keyword triage fails in three ways (SPEC A1): misrouting adds days of internal handoffs; urgent
cases (fraud, unauthorized transactions, harassing collection) wait in the same queue as routine
ones; and agents spend minutes reading long narratives before acting. Cleaned narratives have a
median of 136 words and a 90th percentile of 421 words (reports/m2_data_stats.md).

## Task framing

| Sub-task | Type | Output |
|---|---|---|
| Product | single-label, 10 classes | product category |
| Issue | single-label, long-tailed, 34 classes | issue, top 3 with probabilities |
| Priority | binary on a derived proxy label | HIGH / NORMAL with a score |
| Routing | deterministic table (configs/routing.yaml) | destination team |
| Confidence gate | calibrated probability vs threshold | AUTO or HUMAN_REVIEW with a reason |

Summarization was a stretch goal and was not attempted.

## Users

- **Complaint-handling agent** (primary): the complaint should arrive in the right queue.
- **Queue manager**: urgent cases should surface first.
- **Compliance officer**: every decision must be auditable (model version, scores, route).

## Objective and success metrics

Reduce the time to the first correct assignment and surface high-priority complaints earlier,
while a person stays in control of uncertain cases (SPEC A4). Model targets (SPEC A5, all
[target]): product macro-F1 at least 5 points above the TF-IDF baseline, issue top-3 accuracy at
least 85%, HIGH recall at least 85%, ECE below 0.05 after temperature scaling. System targets:
auto-route coverage at least 60% at 95% precision, p95 latency at most 300 ms on CPU. Section 5
reports each against the measured values.

## Scope

In scope: classification, priority, routing, confidence fallback, REST API, monitoring,
Docker deployment, a reviewer UI. Out of scope: automated customer replies, outcome or
compensation decisions, non-English complaints, real company integration, any automated adverse
action (SPEC A7).
