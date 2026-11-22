"""ComplaintIQ reviewer console (SPEC B4 FR7; M5). Run: ``streamlit run ui/app.py``.

Talks to the API at ``CIQ_API_URL``. Stores nothing: the pasted text lives only in this
browser session's widget state and is sent to the API, which scrubs PII before inference.
The last result kept in the session holds labels and scores, never the text.
"""

from __future__ import annotations

import ciq_client as api
import streamlit as st

# Synthetic examples written for the demo (not real complaints).
SAMPLES = {
    "Credit report dispute": (
        "I found an account on my credit report that does not belong to me. I have never "
        "opened an account with this lender. I disputed it with the credit bureau twice and "
        "both times they said the information was verified, but nobody sent me any proof. "
        "Please remove this account from my report."
    ),
    "Unauthorized card charges": (
        "There are three charges on my credit card statement from a store I have never "
        "visited. I called the card company the same day I saw them and reported them as "
        "fraud. They said they would investigate, but last week they told me the charges "
        "are valid and I have to pay them along with interest."
    ),
    "Mortgage payment problem": (
        "My mortgage servicer applied my monthly payment to the wrong month and then charged "
        "me a late fee. I sent them my bank statement showing the payment was made before "
        "the due date. They keep saying the issue is being reviewed, and now the late "
        "payment appears on my credit report."
    ),
}

st.set_page_config(page_title="ComplaintIQ reviewer", page_icon="📝", layout="centered")


@st.cache_data(ttl=60, show_spinner=False)
def _model() -> dict | None:
    try:
        return api.model_info()
    except api.ApiError:
        return None


with st.sidebar:
    st.subheader("Model in use")
    info = _model()
    if info is None:
        st.caption("The API is not responding yet. A free Space can take a minute to wake up.")
    else:
        st.write(f"`{info['model_version']}`")
        tau = info["thresholds"].get("tau")
        if tau is not None:
            st.caption(f"Complaints are routed automatically when product confidence is at "
                       f"least {tau:.2f}; the rest go to human review.")
    st.caption("Decision support only: a person handles every complaint. Paste synthetic or "
               "already-public text only.")

st.title("Triage a complaint")
st.write("Paste the complaint as the customer wrote it. You will see where it would be "
         "routed, why, and how confident the model is.")

sample = st.selectbox("Start from an example (optional)", ["", *SAMPLES], index=0,
                      format_func=lambda k: k or "Write your own")
text = st.text_area("Complaint text", value=SAMPLES.get(sample, ""), height=200,
                    max_chars=10_000, placeholder="At least 20 words in English work best.")

if st.button("Triage complaint", type="primary", disabled=not text.strip()):
    with st.spinner("Triaging"):
        try:
            st.session_state["result"] = api.triage(text)
        except api.ApiError as err:
            st.session_state.pop("result", None)
            st.error(api.error_message(err))

result = st.session_state.get("result")
if result:
    if result["route"] == "AUTO":
        st.success(f"Routed to **{result['team']}**. {api.explain(result)}")
    else:
        st.warning(f"Sent to the **Human Review Queue**. {api.explain(result)}")

    left, right = st.columns(2)
    with left:
        st.markdown("**Product**")
        st.write(result["product"]["label"])
        st.progress(result["product"]["confidence"],
                    text=f"confidence {result['product']['confidence']:.2f}")
    with right:
        st.markdown("**Priority**")
        st.write(result["priority"]["label"])
        st.progress(result["priority"]["score"],
                    text=f"score for high priority {result['priority']['score']:.2f}")

    if result["issue_top3"]:
        st.markdown("**Most likely issues**")
        for item in result["issue_top3"]:
            st.progress(item["p"], text=f"{item['label']} ({item['p']:.2f})")
    st.caption(f"Request `{result['request_id']}` with model `{result['model_version']}` "
               f"in {result['latency_ms']} ms")

    with st.expander("Correct this result"):
        st.write("Change any field that is wrong. Only the changed fields are sent.")
        with st.form("correction"):
            product = st.text_input("Product", value=result["product"]["label"])
            top_issue = result["issue_top3"][0]["label"] if result["issue_top3"] else ""
            issue = st.text_input("Issue", value=top_issue)
            priority = st.selectbox("Priority", api.PRIORITIES,
                                    index=api.PRIORITIES.index(result["priority"]["label"]))
            team = st.text_input("Team", value=result["team"])
            if st.form_submit_button("Send correction"):
                try:
                    payload = api.feedback_payload(result, product, issue, priority, team)
                    api.send_feedback(payload)
                    st.success("Correction sent. It is linked to this request in the audit log.")
                except ValueError as err:
                    st.info(str(err))
                except api.ApiError as err:
                    st.error(api.error_message(err))
