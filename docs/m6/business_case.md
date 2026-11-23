# Business case (SPEC A5)

Owner: P3 (Udita). Every computed value is in reports/m6/derived_numbers.md.

## Formula

agent-minutes saved per day = complaints per day x auto-route coverage x minutes saved per manual
triage

| input | value | kind |
|---|---|---|
| complaints per day | 5,000 | [assumption], the illustrative SPEC A5 volume |
| auto-route coverage | 0.7261 at precision 0.9356 | **test, one-shot** (reports/m4/test_results.md) |
| minutes saved per triage | 1.5 | [assumption], the illustrative SPEC A5 value |

Result: 5,446 agent-minutes a day, about 90.8 agent-hours (derived). Coverage is the only measured
input; the volume and the minutes saved are assumptions to replace with a real bank's numbers.

## Sensitivity (agent-hours a day at test coverage)

| complaints a day | 1.0 min | 1.5 min | 2.0 min |
|---|---|---|---|
| 2,000 | 24.2 | 36.3 | 48.4 |
| 5,000 | 60.5 | 90.8 | 121.0 |
| 10,000 | 121.0 | 181.5 | 242.0 |

## The cost side

- At precision 0.9356, a share of 0.064 of auto-routed complaints reaches the wrong team (derived)
  and needs a re-route, the failure the product exists to reduce. Raising tau lowers that share and
  the coverage together (curve in reports/m4/calibration_report.md, for example 0.6449 coverage at
  0.9677 precision on val-B).
- The 0.274 of test complaints that go to human review (derived) still need a person: the system
  removes work, it does not remove the queue.
- Running cost on the free tier is zero; the mean inference cost is 10.83 CPU-seconds per 1,000
  requests on one laptop core (reports/m4/inference_benchmark.md). A price per CPU-hour was never
  agreed, so no money figure is given.

## What the estimate does not include

Faster handling of urgent cases (HIGH recall 0.834 on test) is a benefit the formula does not
count. Misrouting costs, agent training and integration work are not counted either.
