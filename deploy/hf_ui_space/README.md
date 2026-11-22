---
title: ComplaintIQ Reviewer
emoji: 📝
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8501
pinned: false
short_description: Reviewer console for the ComplaintIQ triage API
---

# ComplaintIQ reviewer console

Paste a consumer complaint, see the predicted product, top-3 issues, priority, route and team
with confidence scores, and send a correction when the result is wrong. Calls the ComplaintIQ
API whose URL is set in the `CIQ_API_URL` Space variable. Nothing you paste is stored by this
console; the API scrubs PII before inference and keeps only a hash of the text.

Please paste synthetic or already-public text only.

Source: https://github.com/udita-0707/complaintiq
