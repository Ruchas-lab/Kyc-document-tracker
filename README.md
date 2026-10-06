# KYC Document Verification and Remediation Tracker

A tool that reviews corporate client KYC files the way an onboarding or periodic review
analyst does: checking each file against a risk-based document checklist, testing document
validity, reviewing beneficial ownership and screening status, and turning every gap into a
ranked remediation task with an owner and a due date.

It also drafts the client document request, so a finding becomes an action rather than a row
in a report.

---

## Why this exists

The daily workload in KYC operations is not building models. It is collecting documents,
checking they are current and verified, working out who owns the entity, and chasing what is
missing. Files go stale, requests sit unanswered, and review dates slip.

This project mirrors that workflow end to end: from a client file to a prioritised work queue
to a ready-to-send request.

---

## What it does

### 1. Risk-based document checklist

Required documents depend on the entity type and the client's risk tier.

- **Base documents for every client:** registry extract, UBO register extract, articles of
  association, director or signatory ID, authorised signatory list, FATCA/CRS self-certification
- **Entity-type additions:** for example a fund also needs its prospectus and regulatory
  licence, a trust needs its trust deed, a financial services entity needs its licence
- **Risk-tier additions:** medium risk adds a source of funds declaration, high risk adds source
  of wealth evidence

The Luxembourg registers (RCS and RBE) are used as the reference, with an "or equivalent"
for clients domiciled elsewhere.

### 2. Document validity testing

Every required document gets one verdict:

| Verdict | Meaning |
|---------|---------|
| VALID | Received, verified and within its validity window |
| EXPIRING_SOON | Valid but expires inside the configurable warning window |
| EXPIRED | Past its validity window or printed expiry date |
| UNVERIFIED | Received but not yet verified by an analyst |
| OUTSTANDING | Requested from the client and not yet received |
| MISSING | Required, with no request or receipt on file |

Validity follows one of three rules per document: valid for a fixed period from issue date
(registry extracts, proof of address, financial statements), valid until the printed expiry
date (ID documents), or no expiry (articles, signatory lists, declarations).

### 3. Beneficial ownership and screening review

- A natural person holding **more than 25%** is treated as a UBO, in line with the EU AMLD
  beneficial ownership definition
- If nobody exceeds the threshold, the file is flagged until further ownership layers are
  traced or the senior managing official fallback is documented
- If less than 75% of ownership is traced to natural persons, the file is flagged
- Every owner must be identity-verified and screened. Unscreened owners and unresolved
  potential matches are high severity
- A PEP beneficial owner on a client not rated HIGH raises a rating inconsistency finding

### 4. Severity, owners and SLAs

Each finding gets a severity, an owning team and a due date.

| Severity | SLA | Examples |
|----------|-----|----------|
| HIGH | 7 days | Expired or missing critical document, unscreened owner, UBO gap |
| MEDIUM | 21 days | Unverified document, ownership not fully traced |
| LOW | 45 days | Document expiring soon, request recently sent |

Outstanding client requests follow an escalation ladder by days outstanding: awaiting client,
first chase (14 days), second chase (30 days), and escalation to Compliance with a view to
restriction (45+ days).

### 5. Periodic review tracking

Review cycles follow the risk tier (12 months high, 3 years medium, 5 years low). The tool
flags overdue reviews and shows reviews falling due in the next 90 days.

### 6. Client document request drafting

For any client, the tool consolidates every client-facing gap (missing, outstanding, expired
and expiring documents, unverified owner IDs) into a single request email with a deadline.
Internal-only findings such as screening and rating issues are deliberately left out because
the client cannot act on them.

---

## Configurable parameters

The sidebar lets a reviewer change the rules and see the portfolio recalculate:

- **Reference date:** the "as of" date for all validity and ageing calculations
- **Expiring-soon window:** how early to warn before a document expires
- **Registry and address proof max age:** the validity window for extracts

Checklist and rules, SLAs and the escalation ladder are documented on the Checklist and Rules
page.

---

## Design notes

**Thresholds are illustrative.** A three-month validity window for registry extracts, the
review cycles, and the SLAs reflect common internal policy patterns, not legal requirements.
Each firm sets its own in its KYC policy, which is why the validity window is configurable
rather than hard-coded. The 25% beneficial ownership threshold follows the EU AMLD definition.

**Critical documents.** Registry extract, UBO register extract, director ID, and source of
funds and wealth evidence are treated as critical. A gap on any of them is high severity
regardless of tier. Other gaps are medium severity, rising to high for high-risk clients.

**Status logic.** A client is ESCALATE if it has any high-severity finding, REMEDIATION if it
has medium-severity findings, REVIEW SOON if it has only low-severity items, and COMPLETE
otherwise.

**Calibration.** The synthetic portfolio initially produced an unrealistic backlog, with
more than half of clients in escalation. Defect rates in the data generator were tuned until
the distribution looked like a plausible working queue (roughly 31% complete, 32% in
remediation, 25% in escalation, 12% review soon). The engine rules were left unchanged,
because the right fix for an unrealistic dataset is the data, not the control logic.

---

## Running it

```bash
pip install -r requirements.txt
python generate_data.py      # creates the synthetic portfolio
streamlit run app.py
```

---

## Data

The dataset is synthetic: 120 corporate clients across five entity types and sixteen
jurisdictions, 254 beneficial owners, and about 1,060 document records.

Defects are deliberately embedded so the rules can be checked against known cases: stale
registry extracts, expired director IDs, outstanding requests of varying age, unverified
documents, unscreened owners, partially traced ownership structures, PEP owners on
inconsistently rated clients, and overdue periodic reviews.

No real client data is used.

---

## Project structure

```
kyc-document-tracker/
├── app.py              # Streamlit dashboard (4 views)
├── kyc_engine.py       # Checklist, validity rules, findings, client status
├── outreach.py         # Client document request drafting
├── generate_data.py    # Synthetic portfolio generator
├── data/
│   ├── clients.csv
│   ├── documents.csv
│   └── ubos.csv
└── requirements.txt
```

---

## Limitations

This is a demonstration, not production software. A deployed KYC platform would also need:
document upload and OCR, integration with sanctions, PEP and adverse media screening
providers, direct registry lookups, a case management system with audit trail and four-eyes
sign-off, ownership structure visualisation across multiple layers, and policy thresholds
set and approved by the firm's compliance function.

Findings here are generated from the data on file. A real analyst still judges whether a
flagged item is a genuine gap, an acceptable exception, or a false positive.
