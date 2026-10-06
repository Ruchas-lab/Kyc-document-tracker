"""
KYC Rules Engine

Evaluates a corporate client file against a risk-based document checklist,
validity rules, beneficial ownership requirements, screening status and
periodic review cycles. Produces document-level verdicts, severity-ranked
remediation findings with SLAs, and a per-client KYC status.
"""
import pandas as pd
from datetime import timedelta

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

REG_RCS = "Registry Extract (RCS/equiv.)"
REG_RBE = "UBO Register Extract (RBE/equiv.)"
ARTICLES = "Articles of Association"
DIR_ID = "Director / Signatory ID"
ADDRESS = "Proof of Registered Address"
FIN_STMT = "Audited Financial Statements"
SIG_LIST = "Authorised Signatory List"
FATCA = "FATCA / CRS Self-Certification"
LICENCE = "Regulatory Licence / Authorisation"
PROSPECTUS = "Fund Prospectus / Offering Document"
TRUST_DEED = "Trust Deed / Foundation Charter"
SOF = "Source of Funds Declaration"
SOW = "Source of Wealth Evidence"

# mode: "age"    -> valid for max_age days from issue date
#       "expiry" -> valid until the expiry date printed on the document
#       "none"   -> no expiry; checked for presence and verification only
# critical: a gap on this document is treated as high severity regardless of tier
DOC_RULES = {
    REG_RCS:    {"mode": "age", "max_age": 90, "critical": True},
    REG_RBE:    {"mode": "age", "max_age": 90, "critical": True},
    ARTICLES:   {"mode": "none", "critical": False},
    DIR_ID:     {"mode": "expiry", "critical": True},
    ADDRESS:    {"mode": "age", "max_age": 90, "critical": False},
    FIN_STMT:   {"mode": "age", "max_age": 548, "critical": False},
    SIG_LIST:   {"mode": "none", "critical": False},
    FATCA:      {"mode": "none", "critical": False},
    LICENCE:    {"mode": "none", "critical": False},
    PROSPECTUS: {"mode": "none", "critical": False},
    TRUST_DEED: {"mode": "none", "critical": False},
    SOF:        {"mode": "none", "critical": True},
    SOW:        {"mode": "none", "critical": True},
}
# Documents whose validity window follows the configurable "extract max age"
EXTRACT_DOCS = [REG_RCS, REG_RBE, ADDRESS]

BASE_DOCS = [REG_RCS, REG_RBE, ARTICLES, DIR_ID, SIG_LIST, FATCA]

ENTITY_EXTRA = {
    "Operating Company":         [ADDRESS, FIN_STMT],
    "Holding Company":           [ADDRESS, FIN_STMT],
    "Investment Fund":           [PROSPECTUS, LICENCE, FIN_STMT],
    "Financial Services Entity": [LICENCE, ADDRESS, FIN_STMT],
    "Trust / Foundation":        [TRUST_DEED, ADDRESS],
}
TIER_EXTRA = {"LOW": [], "MEDIUM": [SOF], "HIGH": [SOF, SOW]}

# Periodic review cycle by risk tier (days). Illustrative risk-based cycle.
REVIEW_CYCLE_DAYS = {"HIGH": 365, "MEDIUM": 1095, "LOW": 1825}
REVIEW_CYCLE_LABEL = {"HIGH": "12 months", "MEDIUM": "3 years", "LOW": "5 years"}

# Remediation SLA by severity (days from identification)
SLA_DAYS = {"HIGH": 7, "MEDIUM": 21, "LOW": 45}
SEVERITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

# Beneficial ownership: natural persons holding MORE than this % are UBOs
UBO_THRESHOLD = 25.0
MIN_TRACED_PCT = 75.0

ESCALATION_LADDER = [
    {"Days outstanding": "0-13", "Stage": "Awaiting client", "Severity": "LOW", "Owner": "KYC Analyst"},
    {"Days outstanding": "14-29", "Stage": "First chase", "Severity": "MEDIUM", "Owner": "KYC Analyst"},
    {"Days outstanding": "30-44", "Stage": "Second chase", "Severity": "HIGH", "Owner": "KYC Analyst"},
    {"Days outstanding": "45+", "Stage": "Escalate to Compliance, consider restriction", "Severity": "HIGH", "Owner": "Compliance Officer"},
]


def required_documents(entity_type, risk_tier):
    """Document checklist for a client: base + entity-type + risk-tier add-ons."""
    docs = list(BASE_DOCS)
    for d in ENTITY_EXTRA.get(entity_type, []) + TIER_EXTRA.get(risk_tier, []):
        if d not in docs:
            docs.append(d)
    return docs


def get_rules(extract_max_age=90):
    """Return validity rules, applying the configurable extract max age."""
    rules = {k: dict(v) for k, v in DOC_RULES.items()}
    for d in EXTRACT_DOCS:
        rules[d]["max_age"] = extract_max_age
    return rules


def escalation_stage(days_outstanding):
    if days_outstanding >= 45:
        return "Escalate to Compliance, consider restriction"
    if days_outstanding >= 30:
        return "Second chase"
    if days_outstanding >= 14:
        return "First chase"
    return "Awaiting client"


# ---------------------------------------------------------------------------
# DOCUMENT EVALUATION
# ---------------------------------------------------------------------------

def evaluate_documents(clients, docs, ref_date, expiring_window=30, extract_max_age=90):
    """
    Evaluate every required document for every client.
    Verdicts: VALID, EXPIRING_SOON, EXPIRED, UNVERIFIED, OUTSTANDING, MISSING.
    """
    ref = pd.Timestamp(ref_date)
    rules = get_rules(extract_max_age)
    lookup = {(r.client_id, r.doc_type): r for r in docs.itertuples(index=False)}
    rows = []

    for c in clients.itertuples(index=False):
        for dt in required_documents(c.entity_type, c.risk_tier):
            rule = rules[dt]
            rec = lookup.get((c.client_id, dt))
            eff = pd.NaT
            days_to_exp = None
            days_out = None
            issue = pd.NaT
            req = pd.NaT
            verified = False

            if rec is None:
                verdict = "MISSING"
            elif rec.status == "REQUESTED":
                verdict = "OUTSTANDING"
                req = rec.requested_date
                days_out = (ref - req).days
            else:
                issue = rec.issue_date
                verified = bool(rec.verified)
                if rule["mode"] == "age":
                    eff = issue + timedelta(days=rule["max_age"])
                elif rule["mode"] == "expiry":
                    eff = rec.expiry_date
                if not pd.isna(eff):
                    days_to_exp = (eff - ref).days

                if days_to_exp is not None and days_to_exp < 0:
                    verdict = "EXPIRED"
                elif not verified:
                    verdict = "UNVERIFIED"
                elif days_to_exp is not None and days_to_exp <= expiring_window:
                    verdict = "EXPIRING_SOON"
                else:
                    verdict = "VALID"

            rows.append({
                "client_id": c.client_id,
                "doc_type": dt,
                "critical": rule["critical"],
                "verdict": verdict,
                "issue_date": issue,
                "effective_expiry": eff,
                "days_to_expiry": days_to_exp,
                "requested_date": req,
                "days_outstanding": days_out,
                "verified": verified,
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# FINDINGS
# ---------------------------------------------------------------------------

FINDING_COLUMNS = [
    "finding_id", "client_id", "client_name", "risk_tier", "category",
    "finding_type", "severity", "item", "detail", "owner", "sla_days",
    "due_date", "days_outstanding", "escalation_stage",
]


def build_findings(clients, doc_eval, ubos, ref_date):
    """Generate severity-ranked remediation findings with owners and SLAs."""
    ref = pd.Timestamp(ref_date)
    cl = clients.set_index("client_id")
    rows = []

    def add(cid, category, ftype, sev, item, detail, owner, days_out=None, stage=""):
        c = cl.loc[cid]
        sla = SLA_DAYS[sev]
        rows.append({
            "client_id": cid, "client_name": c.client_name, "risk_tier": c.risk_tier,
            "category": category, "finding_type": ftype, "severity": sev,
            "item": item, "detail": detail, "owner": owner, "sla_days": sla,
            "due_date": ref + timedelta(days=sla),
            "days_outstanding": days_out, "escalation_stage": stage,
        })

    # --- Document findings ---
    for r in doc_eval[doc_eval.verdict != "VALID"].itertuples(index=False):
        tier = cl.loc[r.client_id, "risk_tier"]
        crit = bool(r.critical) or tier == "HIGH"

        if r.verdict == "MISSING":
            add(r.client_id, "Document", "Missing document", "HIGH" if crit else "MEDIUM",
                r.doc_type,
                f"{r.doc_type} is required for this customer profile and no request or receipt is on file.",
                "KYC Analyst")
        elif r.verdict == "OUTSTANDING":
            d = int(r.days_outstanding)
            sev = "HIGH" if d >= 30 else ("MEDIUM" if d >= 14 else "LOW")
            add(r.client_id, "Document", "Outstanding request", sev, r.doc_type,
                f"{r.doc_type} requested on {r.requested_date:%d %b %Y}, outstanding for {d} days.",
                "Compliance Officer" if d >= 45 else "KYC Analyst", d, escalation_stage(d))
        elif r.verdict == "EXPIRED":
            add(r.client_id, "Document", "Expired document", "HIGH" if crit else "MEDIUM",
                r.doc_type,
                f"{r.doc_type} expired on {r.effective_expiry:%d %b %Y} ({-int(r.days_to_expiry)} days ago).",
                "KYC Analyst")
        elif r.verdict == "UNVERIFIED":
            add(r.client_id, "Document", "Unverified document", "MEDIUM", r.doc_type,
                f"{r.doc_type} has been received but has not yet been verified by an analyst.",
                "KYC Analyst")
        elif r.verdict == "EXPIRING_SOON":
            add(r.client_id, "Document", "Expiring soon", "LOW", r.doc_type,
                f"{r.doc_type} expires on {r.effective_expiry:%d %b %Y} (in {int(r.days_to_expiry)} days).",
                "KYC Analyst")

    # --- Beneficial ownership, screening and rating findings ---
    for c in clients.itertuples(index=False):
        g = ubos[ubos.client_id == c.client_id]

        if g.empty:
            add(c.client_id, "Beneficial ownership", "No beneficial owner on file", "HIGH",
                "Beneficial ownership",
                "No beneficial owner or senior managing official is recorded for this client.",
                "Compliance Officer")
            continue

        traced = g.ownership_pct.sum()
        above = g[g.ownership_pct > UBO_THRESHOLD]
        if above.empty:
            add(c.client_id, "Beneficial ownership", "UBO identification gap", "HIGH",
                "Beneficial ownership",
                f"No natural person above the {UBO_THRESHOLD:.0f}% threshold identified "
                f"({traced:.0f}% of ownership traced). Trace further ownership layers or "
                f"document the senior managing official fallback.",
                "Compliance Officer")
        elif traced < MIN_TRACED_PCT:
            add(c.client_id, "Beneficial ownership", "Ownership not fully traced", "MEDIUM",
                "Beneficial ownership",
                f"Only {traced:.0f}% of ownership is traced to natural persons. "
                f"Remaining layers should be explained and evidenced.",
                "KYC Analyst")

        for u in g.itertuples(index=False):
            is_ubo = u.ownership_pct > UBO_THRESHOLD
            if not u.id_verified:
                add(c.client_id, "Beneficial ownership", "UBO ID unverified",
                    "HIGH" if is_ubo else "MEDIUM", u.ubo_name,
                    f"Identity of {u.ubo_name} ({u.ownership_pct:.1f}% holder) is not yet verified.",
                    "KYC Analyst")
            if u.screening_status == "NOT_SCREENED":
                add(c.client_id, "Screening", "Not screened", "HIGH", u.ubo_name,
                    f"{u.ubo_name} has not been screened against sanctions and PEP lists.",
                    "Sanctions & Screening")
            elif u.screening_status == "POTENTIAL_MATCH":
                add(c.client_id, "Screening", "Potential match unresolved", "HIGH", u.ubo_name,
                    f"Screening returned a potential match for {u.ubo_name} that has not been dispositioned.",
                    "Sanctions & Screening")

        if g.pep_flag.any() and c.risk_tier != "HIGH":
            peps = ", ".join(g[g.pep_flag].ubo_name.tolist())
            add(c.client_id, "Risk rating", "Rating inconsistent with PEP status", "HIGH",
                "Customer risk rating",
                f"Politically exposed beneficial owner ({peps}) identified but customer is rated "
                f"{c.risk_tier}. Rating review and enhanced due diligence required.",
                "Compliance Officer")

    # --- Periodic review ---
    for c in clients.itertuples(index=False):
        cycle = REVIEW_CYCLE_DAYS[c.risk_tier]
        due = c.last_review_date + timedelta(days=cycle)
        if due < ref:
            overdue = (ref - due).days
            add(c.client_id, "Periodic review", "Periodic review overdue",
                "HIGH" if c.risk_tier == "HIGH" else "MEDIUM", "Periodic review",
                f"Review overdue by {overdue} days. Last review {c.last_review_date:%d %b %Y}; "
                f"{c.risk_tier} risk cycle is {REVIEW_CYCLE_LABEL[c.risk_tier]}.",
                "Relationship Manager")

    if not rows:
        return pd.DataFrame(columns=FINDING_COLUMNS)

    df = pd.DataFrame(rows)
    df["_s"] = df.severity.map(SEVERITY_ORDER)
    df = df.sort_values(["_s", "client_id"]).drop(columns="_s").reset_index(drop=True)
    df.insert(0, "finding_id", [f"F{3000 + i}" for i in range(len(df))])
    return df[FINDING_COLUMNS]


# ---------------------------------------------------------------------------
# CLIENT SUMMARY
# ---------------------------------------------------------------------------

def kyc_status(row):
    if row.high_findings > 0:
        return "ESCALATE"
    if row.medium_findings > 0:
        return "REMEDIATION"
    if row.open_findings > 0:
        return "REVIEW SOON"
    return "COMPLETE"


def client_summary(clients, doc_eval, findings, ref_date):
    """Per-client KYC status, document readiness and next review date."""
    ref = pd.Timestamp(ref_date)
    s = clients.copy()

    ready = (doc_eval.assign(ok=doc_eval.verdict.isin(["VALID", "EXPIRING_SOON"]))
             .groupby("client_id").agg(required_docs=("doc_type", "count"), valid_docs=("ok", "sum"))
             .reset_index())
    s = s.merge(ready, on="client_id", how="left")
    s["doc_readiness_pct"] = (s.valid_docs / s.required_docs * 100).round(0)

    if findings.empty:
        s["open_findings"] = 0
        s["high_findings"] = 0
        s["medium_findings"] = 0
    else:
        f = findings.groupby("client_id").agg(
            open_findings=("finding_id", "count"),
            high_findings=("severity", lambda x: int((x == "HIGH").sum())),
            medium_findings=("severity", lambda x: int((x == "MEDIUM").sum())),
        ).reset_index()
        s = s.merge(f, on="client_id", how="left")
        for col in ["open_findings", "high_findings", "medium_findings"]:
            s[col] = s[col].fillna(0).astype(int)

    s["kyc_status"] = s.apply(kyc_status, axis=1)
    s["next_review_due"] = s.last_review_date + s.risk_tier.map(
        lambda t: pd.Timedelta(days=REVIEW_CYCLE_DAYS[t]))
    s["days_to_review"] = (s.next_review_due - ref).dt.days
    return s
