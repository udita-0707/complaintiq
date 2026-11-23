# Demo run sheet (M6)

Owner: P4 (Aman). The demo is on slide 11 of reports/m6/ComplaintIQ_deck.pptx (presenter 4). Inputs are synthetic
(demo/examples.json); no real complaint appears on screen.

## Before the session

- [ ] There is no public deployment, so the demo runs on the presenter's laptop. 10 minutes before:
      `make space`, then `docker compose -f docker/docker-compose.serve.yml up -d`, check
      `curl -s http://127.0.0.1:8000/health` shows `"model_loaded":true`, then
      `make ui URL=http://127.0.0.1:8000` and open the console in the browser.
- [ ] The laptop needs the frozen model in `models/` (Udita's clone, or a copy that `make space`
      verifies against the manifest).
- [ ] Screen recording of a full rehearsal saved locally (the fallback).

## Run sheet (about 3 minutes)

| time | action | say |
|---|---|---|
| 0:00 | UI open, sidebar shows the model version | "This is what an agent sees." |
| 0:15 | load "Unauthorized card charges", click Triage complaint | route, team, product confidence, issue bars |
| 1:00 | type "My bank charged me a fee twice." and triage | short input goes to a person, with the reason |
| 1:40 | open "Correct this result", change the product, send | corrections are linked to the request in the audit log |
| 2:20 | optional: open `/metrics`, point at routes and PII counters | monitoring without raw text |
| 2:50 | back to the deck | continue with slide 12 (limits, next steps, questions) |

## If something fails

| problem | do this |
|---|---|
| UI says the API is not responding | check the container (`docker compose ... ps`), restart it; cold start is about 3.4 s |
| the laptop setup fails | play the rehearsal recording and narrate |
| a result differs from the rehearsal | say so; predictions depend on the model, not on a script |

## Rehearsal log (definition of done: every member can explain every stage)

| date | presenters | stages explained by each member | timing | issues and fixes |
|---|---|---|---|---|
| TODO | | Kalash: | | |
| | | Dally: | | |
| | | Udita: | | |
| | | Aman: | | |
