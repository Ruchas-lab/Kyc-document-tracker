"""
KYC Document Verification and Remediation Tracker
Streamlit dashboard for corporate client file review, document validity
checks, beneficial ownership review and remediation tracking.
"""
from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from kyc_engine import (
    evaluate_documents, build_findings, client_summary, required_documents,
    get_rules, ENTITY_EXTRA, TIER_EXTRA, BASE_DOCS, DOC_RULES, REVIEW_CYCLE_DAYS,
    REVIEW_CYCLE_LABEL, SLA_DAYS, ESCALATION_LADDER, UBO_THRESHOLD, MIN_TRACED_PCT,
)
from outreach import draft_document_request

st.set_page_config(page_title="KYC Verification Tracker", layout="wide",
                   initial_sidebar_state="expanded")

ACCENT = "#2c3e6b"
STATUS_COLORS = {"COMPLETE": "#27ae60", "REVIEW SOON": "#f1c40f",
                 "REMEDIATION": "#e67e22", "ESCALATE": "#c0392b"}
SEV_COLORS = {"HIGH": "#c0392b", "MEDIUM": "#e67e22", "LOW": "#f1c40f"}
STATUS_ORDER = {"ESCALATE": 0, "REMEDIATION": 1, "REVIEW SOON": 2, "COMPLETE": 3}
TIER_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

st.markdown("""
<style>
.main .block-container {padding-top: 2rem;}
h1 {color: #2c3e6b; font-size: 1.9rem;}
h2 {color: #2c3e6b; font-size: 1.3rem; margin-top: 1.2rem;}
.stMetric {background: #f8f9fa; padding: 0.8rem; border-radius: 6px;
           border-left: 3px solid #2c3e6b;}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_data():
    clients = pd.read_csv("data/clients.csv", parse_dates=["onboarding_date", "last_review_date"])
    docs = pd.read_csv("data/documents.csv", parse_dates=["issue_date", "expiry_date", "requested_date"])
    ubos = pd.read_csv("data/ubos.csv")
    return clients, docs, ubos


@st.cache_data
def run_engine(ref_iso, expiring_window, extract_age):
    clients, docs, ubos = load_data()
    doc_eval = evaluate_documents(clients, docs, ref_iso, expiring_window, extract_age)
    findings = build_findings(clients, doc_eval, ubos, ref_iso)
    summary = client_summary(clients, doc_eval, findings, ref_iso)
    return doc_eval, findings, summary


clients, docs, ubos = load_data()

# ===== SIDEBAR =====
st.sidebar.markdown("### KYC Verification Tracker")
st.sidebar.caption("Risk-based document checklist, validity checks, beneficial ownership review and remediation tracking.")
st.sidebar.markdown("---")

page = st.sidebar.radio("View", [
    "Portfolio Overview",
    "Remediation Queue",
    "Client File",
    "Checklist and Rules",
])

st.sidebar.markdown("---")
st.sidebar.markdown("**Configuration**")
ref_date = st.sidebar.date_input("Reference date", value=date(2026, 10, 4))
expiring_window = st.sidebar.slider("Expiring-soon window (days)", 7, 90, 30)
extract_age = st.sidebar.slider("Registry and address proof max age (days)", 30, 180, 90, step=15)

ref_iso = ref_date.isoformat()
doc_eval, findings, summary = run_engine(ref_iso, expiring_window, extract_age)

st.sidebar.markdown("---")
st.sidebar.caption("Synthetic data. Built to demonstrate KYC file review logic.")


# ===== PAGE 1: OVERVIEW =====
if page == "Portfolio Overview":
    st.title("Portfolio Overview")
    st.caption(f"{len(clients)} corporate clients · reference date {ref_date:%d %b %Y}")

    complete_pct = (summary.kyc_status == "COMPLETE").mean() * 100
    overdue_reviews = int((findings.finding_type == "Periodic review overdue").sum()) if not findings.empty else 0
    high_findings = int((findings.severity == "HIGH").sum()) if not findings.empty else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Clients", len(clients))
    c2.metric("KYC complete", f"{complete_pct:.0f}%")
    c3.metric("In escalation", int((summary.kyc_status == "ESCALATE").sum()))
    c4.metric("Open findings", len(findings))
    c5.metric("High severity", high_findings)
    c6.metric("Reviews overdue", overdue_reviews)

    st.markdown("---")
    left, right = st.columns(2)

    with left:
        st.subheader("KYC status by risk tier")
        ct = summary.groupby(["risk_tier", "kyc_status"]).size().reset_index(name="clients")
        fig = px.bar(ct, x="risk_tier", y="clients", color="kyc_status",
                     color_discrete_map=STATUS_COLORS,
                     category_orders={"risk_tier": ["HIGH", "MEDIUM", "LOW"],
                                      "kyc_status": ["COMPLETE", "REVIEW SOON", "REMEDIATION", "ESCALATE"]},
                     labels={"risk_tier": "Risk tier", "clients": "Clients", "kyc_status": "Status"})
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

    with right:
        st.subheader("Open findings by type")
        if findings.empty:
            st.info("No open findings.")
        else:
            by_type = findings.groupby(["finding_type", "severity"]).size().reset_index(name="count")
            order = findings.finding_type.value_counts().index.tolist()[::-1]
            fig = px.bar(by_type, x="count", y="finding_type", color="severity", orientation="h",
                         color_discrete_map=SEV_COLORS,
                         category_orders={"finding_type": order, "severity": ["HIGH", "MEDIUM", "LOW"]},
                         labels={"count": "Findings", "finding_type": "", "severity": "Severity"})
            fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, width="stretch")

    st.markdown("---")
    left, right = st.columns(2)

    with left:
        st.subheader("Outstanding document requests: ageing")
        out = doc_eval[doc_eval.verdict == "OUTSTANDING"].copy()
        if out.empty:
            st.info("No outstanding requests.")
        else:
            bins = [0, 14, 30, 45, 10000]
            labels = ["0-13 days", "14-29 days", "30-44 days", "45+ days"]
            out["bucket"] = pd.cut(out.days_outstanding, bins=bins, labels=labels, right=False)
            ageing = out.bucket.value_counts().reindex(labels).fillna(0).reset_index()
            ageing.columns = ["bucket", "requests"]
            fig = go.Figure(go.Bar(
                x=ageing.bucket, y=ageing.requests,
                marker_color=["#95a5a6", "#f1c40f", "#e67e22", "#c0392b"],
                text=ageing.requests.astype(int), textposition="outside"))
            fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0),
                              yaxis_title="Requests", xaxis_title="")
            st.plotly_chart(fig, width="stretch")

    with right:
        st.subheader("Document verdicts across the portfolio")
        v = doc_eval.verdict.value_counts().reset_index()
        v.columns = ["verdict", "documents"]
        vcolors = {"VALID": "#27ae60", "EXPIRING_SOON": "#f1c40f", "UNVERIFIED": "#e67e22",
                   "OUTSTANDING": "#d35400", "EXPIRED": "#c0392b", "MISSING": "#7f8c8d"}
        fig = px.pie(v, names="verdict", values="documents", hole=0.55,
                     color="verdict", color_discrete_map=vcolors)
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")

    st.markdown("---")
    st.subheader("Periodic reviews due in the next 90 days")
    upcoming = summary[(summary.days_to_review >= 0) & (summary.days_to_review <= 90)].sort_values("days_to_review")
    if upcoming.empty:
        st.info("No periodic reviews fall due in the next 90 days.")
    else:
        view = upcoming[["client_id", "client_name", "risk_tier", "relationship_manager",
                         "last_review_date", "next_review_due", "days_to_review"]].copy()
        view["last_review_date"] = view.last_review_date.dt.strftime("%d %b %Y")
        view["next_review_due"] = view.next_review_due.dt.strftime("%d %b %Y")
        st.dataframe(view, width="stretch", hide_index=True, column_config={
            "client_id": "Client ID", "client_name": "Name", "risk_tier": "Tier",
            "relationship_manager": "Relationship manager", "last_review_date": "Last review",
            "next_review_due": "Next due", "days_to_review": "Days to due"})


# ===== PAGE 2: REMEDIATION QUEUE =====
elif page == "Remediation Queue":
    st.title("Remediation Queue")
    st.caption("Open findings ranked by severity. Each carries an owner and an SLA due date.")

    if findings.empty:
        st.info("No open findings.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        sev = f1.multiselect("Severity", ["HIGH", "MEDIUM", "LOW"], default=["HIGH", "MEDIUM", "LOW"])
        ftype = f2.multiselect("Finding type", sorted(findings.finding_type.unique()), default=[])
        owner = f3.multiselect("Owner", sorted(findings.owner.unique()), default=[])
        tier = f4.multiselect("Risk tier", ["HIGH", "MEDIUM", "LOW"], default=[])

        view = findings[findings.severity.isin(sev)]
        if ftype:
            view = view[view.finding_type.isin(ftype)]
        if owner:
            view = view[view.owner.isin(owner)]
        if tier:
            view = view[view.risk_tier.isin(tier)]

        m1, m2, m3 = st.columns(3)
        m1.metric("Findings shown", len(view))
        m2.metric("Clients affected", view.client_id.nunique())
        m3.metric("Escalated to Compliance", int((view.escalation_stage.str.startswith("Escalate")).sum()))

        show = view[["finding_id", "client_id", "client_name", "risk_tier", "severity",
                     "finding_type", "item", "detail", "owner", "due_date", "escalation_stage"]].copy()
        show["due_date"] = show.due_date.dt.strftime("%d %b %Y")
        st.dataframe(show, width="stretch", hide_index=True, column_config={
            "finding_id": "ID", "client_id": "Client ID", "client_name": "Name",
            "risk_tier": "Tier", "severity": "Severity", "finding_type": "Type",
            "item": "Item", "detail": st.column_config.TextColumn("Detail", width="large"),
            "owner": "Owner", "due_date": "SLA due", "escalation_stage": "Escalation stage"})

        st.download_button("Download filtered queue (.csv)", show.to_csv(index=False),
                           file_name="kyc_remediation_queue.csv", mime="text/csv")

        st.markdown("---")
        st.subheader("Workload by owner")
        wl = view.groupby(["owner", "severity"]).size().reset_index(name="findings")
        fig = px.bar(wl, x="owner", y="findings", color="severity", color_discrete_map=SEV_COLORS,
                     category_orders={"severity": ["HIGH", "MEDIUM", "LOW"]},
                     labels={"owner": "", "findings": "Findings", "severity": "Severity"})
        fig.update_layout(height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig, width="stretch")


# ===== PAGE 3: CLIENT FILE =====
elif page == "Client File":
    st.title("Client File")
    st.caption("Document checklist, beneficial ownership and open findings for a single client.")

    ordered = summary.assign(_s=summary.kyc_status.map(STATUS_ORDER), _t=summary.risk_tier.map(TIER_ORDER)
                             ).sort_values(["_s", "_t", "client_id"])
    options = [f"{r.client_id} | {r.client_name} | {r.kyc_status}" for r in ordered.itertuples()]
    choice = st.selectbox("Client", options)
    cid = choice.split(" | ")[0]

    c = summary[summary.client_id == cid].iloc[0]
    c_docs = doc_eval[doc_eval.client_id == cid]
    c_ubos = ubos[ubos.client_id == cid]
    c_find = findings[findings.client_id == cid] if not findings.empty else findings

    st.markdown("---")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("KYC status", c.kyc_status)
    m2.metric("Risk tier", c.risk_tier)
    m3.metric("Document readiness", f"{c.doc_readiness_pct:.0f}%")
    m4.metric("Open findings", int(c.open_findings))
    m5.metric("Next review", f"{c.next_review_due:%d %b %Y}")

    st.write(f"**{c.client_name}** · {c.entity_type} · {c.jurisdiction} · {c.sector} · "
             f"Onboarded {pd.Timestamp(c.onboarding_date):%d %b %Y} · RM {c.relationship_manager}")

    st.markdown("---")
    st.subheader("Document checklist")
    chk = c_docs.copy()
    chk["issue_date"] = chk.issue_date.dt.strftime("%d %b %Y").fillna("n/a")
    chk["effective_expiry"] = chk.effective_expiry.dt.strftime("%d %b %Y").fillna("n/a")
    chk["days_to_expiry"] = pd.to_numeric(chk.days_to_expiry, errors="coerce").astype("Int64")
    chk["critical"] = chk.critical.map({True: "Yes", False: ""})
    chk["verified"] = chk.verified.map({True: "Yes", False: "No"})
    st.dataframe(chk[["doc_type", "critical", "verdict", "issue_date", "effective_expiry",
                      "days_to_expiry", "verified"]],
                 width="stretch", hide_index=True, column_config={
                     "doc_type": "Document", "critical": "Critical", "verdict": "Verdict",
                     "issue_date": "Issued / received", "effective_expiry": "Valid until",
                     "days_to_expiry": "Days left", "verified": "Verified"})

    st.markdown("---")
    left, right = st.columns([1.1, 1])

    with left:
        st.subheader("Beneficial ownership")
        u = c_ubos.copy()
        u["role"] = u.ownership_pct.apply(
            lambda p: f"UBO (>{UBO_THRESHOLD:.0f}%)" if p > UBO_THRESHOLD else "Controlling person")
        u["pep_flag"] = u.pep_flag.map({True: "Yes", False: ""})
        u["id_verified"] = u.id_verified.map({True: "Yes", False: "No"})
        st.dataframe(u[["ubo_name", "nationality", "ownership_pct", "role", "id_verified",
                        "screening_status", "pep_flag"]],
                     width="stretch", hide_index=True, column_config={
                         "ubo_name": "Name", "nationality": "Nat.",
                         "ownership_pct": st.column_config.NumberColumn("Ownership %", format="%.1f"),
                         "role": "Role", "id_verified": "ID verified",
                         "screening_status": "Screening", "pep_flag": "PEP"})
        traced = c_ubos.ownership_pct.sum()
        st.caption(f"{traced:.0f}% of ownership traced to natural persons "
                   f"(minimum expected: {MIN_TRACED_PCT:.0f}%).")

    with right:
        st.subheader("Ownership vs UBO threshold")
        fig = go.Figure(go.Bar(x=c_ubos.ubo_name, y=c_ubos.ownership_pct,
                               marker_color=[ACCENT if p > UBO_THRESHOLD else "#95a5a6"
                                             for p in c_ubos.ownership_pct]))
        fig.add_hline(y=UBO_THRESHOLD, line_dash="dash", line_color="#c0392b",
                      annotation_text=f"{UBO_THRESHOLD:.0f}% threshold", annotation_position="top right")
        fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                          yaxis_title="Ownership %", xaxis_title="", yaxis_range=[0, 100])
        st.plotly_chart(fig, width="stretch")

    st.markdown("---")
    st.subheader("Open findings")
    if c_find.empty:
        st.success("No open findings. KYC file is complete.")
    else:
        for r in c_find.itertuples():
            color = SEV_COLORS[r.severity]
            st.markdown(f"<span style='color:{color};font-weight:600'>{r.severity}</span> · "
                        f"**{r.finding_type}** · {r.item}", unsafe_allow_html=True)
            st.write(r.detail)
            st.caption(f"Owner: {r.owner} · SLA due {r.due_date:%d %b %Y}"
                       + (f" · Stage: {r.escalation_stage}" if r.escalation_stage else ""))

    st.markdown("---")
    st.subheader("Client document request")
    draft = draft_document_request(c, c_find, ref_iso, extract_max_age=extract_age) if not c_find.empty else None
    if draft is None:
        st.info("Nothing to request from the client. Remaining findings are internal actions.")
    else:
        st.code(draft, language=None)
        st.download_button("Download request draft (.txt)", draft,
                           file_name=f"KYC_request_{cid}.txt", mime="text/plain")


# ===== PAGE 4: CHECKLIST AND RULES =====
elif page == "Checklist and Rules":
    st.title("Checklist and Rules")
    st.caption("Risk-based document requirements, validity rules, SLAs and escalation logic.")

    st.subheader("Required documents by entity type")
    entities = list(ENTITY_EXTRA.keys())
    all_docs = list(DOC_RULES.keys())
    matrix = pd.DataFrame({"Document": all_docs})
    for e in entities:
        req = required_documents(e, "LOW")
        matrix[e] = ["Required" if d in req else "" for d in all_docs]
    for t in ["MEDIUM", "HIGH"]:
        matrix[f"{t} tier add-on"] = ["Required" if d in TIER_EXTRA[t] else "" for d in all_docs]
    matrix = matrix[matrix.iloc[:, 1:].apply(lambda r: any(r != ""), axis=1)]
    st.dataframe(matrix, width="stretch", hide_index=True)
    st.caption(f"Base documents for every client: {', '.join(BASE_DOCS)}. "
               f"Tier add-ons are in addition to the entity-type requirements.")

    st.markdown("---")
    st.subheader("Validity rules")
    rules = get_rules(extract_age)
    rr = []
    for d, r in rules.items():
        if r["mode"] == "age":
            validity = f"Valid {r['max_age']} days from issue"
        elif r["mode"] == "expiry":
            validity = "Valid until printed expiry date"
        else:
            validity = "No expiry (presence and verification only)"
        rr.append({"Document": d, "Validity": validity,
                   "Critical": "Yes" if r["critical"] else "",
                   "Gap severity": "HIGH" if r["critical"] else "MEDIUM (HIGH for high-risk tier)"})
    st.dataframe(pd.DataFrame(rr), width="stretch", hide_index=True)

    st.markdown("---")
    left, right = st.columns(2)
    with left:
        st.subheader("Remediation SLAs")
        st.dataframe(pd.DataFrame([{"Severity": k, "SLA (days)": v} for k, v in SLA_DAYS.items()]),
                     width="stretch", hide_index=True)
        st.subheader("Periodic review cycle")
        st.dataframe(pd.DataFrame([{"Risk tier": k, "Review cycle": REVIEW_CYCLE_LABEL[k]}
                                   for k in ["HIGH", "MEDIUM", "LOW"]]),
                     width="stretch", hide_index=True)
    with right:
        st.subheader("Outstanding request escalation ladder")
        st.dataframe(pd.DataFrame(ESCALATION_LADDER), width="stretch", hide_index=True)

    st.markdown("---")
    st.subheader("Beneficial ownership rules")
    st.write(
        f"- A natural person holding more than {UBO_THRESHOLD:.0f}% of ownership is treated as a UBO and must be "
        f"identified and verified.\n"
        f"- If no natural person exceeds {UBO_THRESHOLD:.0f}%, further ownership layers must be traced or the "
        f"senior managing official fallback documented. Otherwise a high-severity finding is raised.\n"
        f"- If less than {MIN_TRACED_PCT:.0f}% of ownership is traced to natural persons, a medium-severity "
        f"finding is raised.\n"
        f"- Every beneficial owner must be screened against sanctions and PEP lists. Unscreened owners and "
        f"unresolved potential matches are high severity.\n"
        f"- A PEP beneficial owner on a client not rated HIGH raises a rating inconsistency finding."
    )
