"""
Client outreach: drafts a consolidated document request for a client,
built from the open findings on its KYC file.
"""
import pandas as pd


def draft_document_request(client, findings, ref_date, deadline_days=14, extract_max_age=90):
    """
    Build a request email listing every item the client needs to provide.
    Internal-only findings (unverified documents, screening, rating) are
    deliberately excluded because they are not client actions.
    Returns None if nothing needs to be requested.
    """
    ref = pd.Timestamp(ref_date)
    deadline = ref + pd.Timedelta(days=deadline_days)
    items = []

    for f in findings.itertuples(index=False):
        if f.finding_type == "Missing document":
            items.append((f.item, "not yet received"))
        elif f.finding_type == "Outstanding request":
            items.append((f.item, f"requested previously, still outstanding after {int(f.days_outstanding)} days"))
        elif f.finding_type == "Expired document":
            items.append((f.item, "current copy has expired, please send an updated version"))
        elif f.finding_type == "Expiring soon":
            items.append((f.item, "due to expire shortly, please send a renewed copy"))
        elif f.finding_type == "UBO ID unverified":
            items.append((f"Certified identification document for {f.item}",
                          "required to complete identity verification"))

    if not items:
        return None

    lines = [
        f"Subject: Updated KYC documentation required - {client.client_name} ({client.client_id})",
        "",
        "Dear Sir or Madam,",
        "",
        f"As part of our ongoing due diligence obligations, we are updating the KYC file for "
        f"{client.client_name}. Please provide the following by {deadline:%d %B %Y}:",
        "",
    ]
    for i, (item, reason) in enumerate(items, 1):
        lines.append(f"{i}. {item}: {reason}")
    lines += [
        "",
        f"Registry and beneficial ownership extracts should be dated within the last {extract_max_age} days. "
        f"Copies of identification documents should be certified where applicable.",
        "",
        "If any of these items have already been sent, please let us know the date and the contact "
        "they were sent to so that we can trace them.",
        "",
        "Kind regards,",
        "KYC Operations",
    ]
    return "\n".join(lines)
