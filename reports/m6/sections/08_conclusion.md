# Conclusion and project status

ComplaintIQ turns a complaint narrative into a calibrated routing suggestion. On the one-shot
test split it auto-routes 0.7261 of complaints at precision 0.9356, keeps issue macro-F1 at 0.498
(close to val), and flags HIGH-priority complaints with recall 0.834. Most remaining errors come
from ambiguous labels and taxonomy changes rather than from the model.

## Status against each milestone's definition of done (SPEC C13)

| milestone | definition of done | status |
|---|---|---|
| M1 | Part A approved, repo created, data downloaded | done |
| M2 | reproducible `make data`; leakage tests pass | done |
| M3 | at least one transformer beats the baseline on val; all runs logged | **partly**: runs logged; transformer only smoke-tested, criterion not met |
| M4 | test results reported once; error taxonomy with counts | done (ONNX int8 and two robustness checks not done) |
| M5 | public URL works; load and failure tests documented | **partly**: load and failure tests documented on the local container (16 of 16 failure tests passed); no public URL (paid plan required) |
| M6 | demo rehearsed; every member can explain every stage | **open** until the rehearsal log in docs/m6/demo_script.md is filled |

## What would improve the system most

1. Adopt the measured iterations (prior correction, softer class weights, issue restricted to the
   predicted product), then recalibrate and re-freeze.
2. Run DistilBERT on a GPU with three seeds and, if it wins, export it to ONNX int8 with the
   agreement check of SPEC C11.
3. Review labels where the error analysis points (credit-reporting issues), hand-check 200
   priority labels, and add the 2023-08 taxonomy to training.
4. Publish the container on a host with a free or paid tier that runs Docker images, then give it a
   persistent audit log and a metrics scraper so drift and correction rates can be tracked over time;
   re-base the PSI alert on a recent reference period, since the replay shows the training reference
   fires every month.
