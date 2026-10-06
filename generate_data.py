"""
Synthetic KYC portfolio generator.

Creates corporate clients, their beneficial owners and document files, with
realistic defects embedded: stale registry extracts, expired director IDs,
outstanding document requests, unverified documents, unscreened owners,
ownership structures that are not fully traced, PEP owners on clients with
an inconsistent rating, and overdue periodic reviews.
"""
import random
import numpy as np
import pandas as pd
from datetime import timedelta

from kyc_engine import required_documents, DOC_RULES, REVIEW_CYCLE_DAYS

random.seed(23)
np.random.seed(23)

REF = pd.Timestamp("2026-10-04")

ENTITY_TYPES = [
    ("Operating Company", 0.30),
    ("Holding Company", 0.25),
    ("Investment Fund", 0.20),
    ("Financial Services Entity", 0.13),
    ("Trust / Foundation", 0.12),
]
JURISDICTIONS = (["LU"] * 8 + ["DE", "FR", "NL", "IE", "CH", "GB", "US", "SG", "MT", "CY"]
                 + ["AE", "PA", "TR", "VG", "KY"])
HIGH_RISK_JURISDICTIONS = {"AE", "PA", "TR", "VG", "KY"}
SECTORS = ["Manufacturing", "Real Estate", "Technology", "Logistics", "Professional Services",
           "Asset Management", "Import/Export", "Energy", "Healthcare",
           "Precious Metals Trading", "Crypto / Digital Assets", "Art & Antiquities"]
HIGH_RISK_SECTORS = {"Precious Metals Trading", "Crypto / Digital Assets", "Art & Antiquities"}

NAME_A = ["Alder", "Meridian", "Corvus", "Lumen", "Vantor", "Nordhaven", "Aurelia", "Brightwell",
          "Kestrel", "Halcyon", "Stratos", "Pinecrest", "Oakmere", "Solstice", "Ardent", "Verity"]
NAME_B = ["Capital", "Holdings", "Partners", "Industries", "Logistics", "Ventures", "Trading",
          "Investments", "Group", "Estates", "Technologies", "Advisory"]
SUFFIX = {"LU": "S.a r.l.", "DE": "GmbH", "FR": "SAS", "NL": "B.V.", "IE": "Ltd", "CH": "AG",
          "GB": "Ltd", "US": "LLC", "SG": "Pte Ltd", "MT": "Ltd", "CY": "Ltd", "AE": "FZE",
          "PA": "S.A.", "TR": "A.S.", "VG": "Ltd", "KY": "Ltd"}
FIRST = ["Alex", "Maria", "Jonas", "Priya", "Chen", "Sofia", "Omar", "Elena", "Lukas", "Amara",
         "Daniel", "Yuki", "Marco", "Ingrid", "Rahul", "Clara", "Hassan", "Nadia"]
LAST = ["Weber", "Laurent", "Singh", "Rossi", "Khan", "Novak", "Martin", "Silva", "Meyer",
        "Okafor", "Hansen", "Costa", "Petrov", "Dubois", "Mehta", "Fischer", "Tanaka", "Kowalski"]
NATIONALITIES = ["DE", "FR", "IN", "GB", "US", "LU", "NL", "IT", "ES", "CH", "AE", "TR", "BR", "SG", "PL"]
RMS = ["Anna Keller", "Marc Dubois", "Sofia Rossi", "Jan de Vries", "Elena Petrova", "Lukas Meier"]


def make_ubos(client_id):
    """Beneficial owners for one client, with occasional tracing and screening gaps."""
    k = random.choices([1, 2, 3, 4], weights=[0.35, 0.35, 0.20, 0.10])[0]
    traced = 100.0 if random.random() < 0.86 else round(random.uniform(35, 70), 1)

    if k == 1:
        shares = [traced]
    else:
        primary = traced * random.uniform(0.4, 0.85)
        rest = np.random.dirichlet(np.ones(k - 1)) * (traced - primary)
        shares = [primary] + list(rest)
    shares = [round(s, 1) for s in shares]

    rows = []
    for s in shares:
        rows.append({
            "client_id": client_id,
            "ubo_name": f"{random.choice(FIRST)} {random.choice(LAST)}",
            "nationality": random.choice(NATIONALITIES),
            "ownership_pct": s,
            "pep_flag": random.random() < 0.05,
            "id_verified": random.random() > 0.03,
            "screening_status": random.choices(
                ["CLEAR", "NOT_SCREENED", "POTENTIAL_MATCH"], weights=[0.96, 0.015, 0.025])[0],
        })
    return rows


def make_portfolio(n=120):
    clients, ubos, used = [], [], set()

    for i in range(n):
        entity = random.choices([e for e, _ in ENTITY_TYPES], [w for _, w in ENTITY_TYPES])[0]
        jur = random.choice(JURISDICTIONS)
        sector = random.choice(SECTORS)
        if entity == "Investment Fund":
            sector = "Asset Management"
        elif entity == "Financial Services Entity":
            sector = random.choice(["Asset Management", "Professional Services"])

        while True:
            name = f"{random.choice(NAME_A)} {random.choice(NAME_B)} {SUFFIX[jur]}"
            if name not in used:
                used.add(name)
                break

        cid = f"KYC-{2001 + i}"
        client_ubos = make_ubos(cid)

        # Risk rating: jurisdiction, sector and structure; PEP only sometimes reflected
        score = 0
        score += 2 if jur in HIGH_RISK_JURISDICTIONS else 0
        score += 2 if sector in HIGH_RISK_SECTORS else 0
        score += 1 if entity == "Trust / Foundation" else 0
        if any(u["pep_flag"] for u in client_ubos) and random.random() < 0.7:
            score += 3
        tier = "HIGH" if score >= 3 else ("MEDIUM" if score >= 1 else "LOW")

        onboarding = REF - timedelta(days=random.randint(120, 2600))
        cycle = REVIEW_CYCLE_DAYS[tier]
        elapsed = (REF - onboarding).days
        if elapsed < cycle - 20:
            last_review = onboarding
        elif random.random() < 0.13:
            last_review = onboarding + timedelta(days=random.randint(0, max(elapsed - cycle - 10, 1)))
        else:
            last_review = REF - timedelta(days=random.randint(10, cycle - 20))

        clients.append({
            "client_id": cid, "client_name": name, "entity_type": entity,
            "jurisdiction": jur, "sector": sector,
            "onboarding_date": onboarding.date(), "last_review_date": last_review.date(),
            "risk_tier": tier, "relationship_manager": random.choice(RMS),
        })
        ubos += client_ubos

    return pd.DataFrame(clients), pd.DataFrame(ubos)


def make_documents(clients):
    rows = []
    for c in clients.itertuples(index=False):
        for dt in required_documents(c.entity_type, c.risk_tier):
            r = random.random()
            base = {"client_id": c.client_id, "doc_type": dt}

            if r < 0.025:  # requested, still outstanding
                rows.append({**base, "status": "REQUESTED", "issue_date": None, "expiry_date": None,
                             "requested_date": (REF - timedelta(days=random.randint(3, 60))).date(),
                             "verified": False})
                continue
            if r < 0.035:  # no record at all
                continue

            rule = DOC_RULES[dt]
            verified = random.random() < 0.98
            issue, expiry = None, None

            if rule["mode"] == "age":
                max_age = rule["max_age"]
                if random.random() < 0.03:
                    age = random.randint(max_age + 5, max_age + 200)
                elif random.random() < 0.04:
                    age = random.randint(max_age - 25, max_age - 2)
                else:
                    age = random.randint(5, max_age - 30)
                issue = REF - timedelta(days=age)
            elif rule["mode"] == "expiry":
                x = random.random()
                if x < 0.03:
                    expiry = REF - timedelta(days=random.randint(3, 200))
                elif x < 0.07:
                    expiry = REF + timedelta(days=random.randint(2, 28))
                else:
                    expiry = REF + timedelta(days=random.randint(60, 1800))
                issue = expiry - timedelta(days=3650)
            else:
                issue = REF - timedelta(days=random.randint(60, 1500))

            rows.append({**base, "status": "RECEIVED",
                         "issue_date": issue.date() if issue is not None else None,
                         "expiry_date": expiry.date() if expiry is not None else None,
                         "requested_date": None, "verified": verified})
    return pd.DataFrame(rows)


if __name__ == "__main__":
    clients, ubos = make_portfolio(120)
    docs = make_documents(clients)
    clients.to_csv("data/clients.csv", index=False)
    ubos.to_csv("data/ubos.csv", index=False)
    docs.to_csv("data/documents.csv", index=False)
    print(f"Generated {len(clients)} clients, {len(ubos)} beneficial owners, {len(docs)} document records")
    print(clients.risk_tier.value_counts().to_dict())
