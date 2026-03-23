"""
Fetches Hospitable reservations + PriceLabs listings and saves to data.json.
Run this script to refresh the data before opening the dashboard.
"""

import os
import csv
import json
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

HOSPITABLE_BASE = "https://public.api.hospitable.com/v2"
HOSPITABLE_HEADERS = {
    "Authorization": f"Bearer {os.getenv('HOSPITABLE_API_TOKEN')}",
    "Accept": "application/json",
}

PRICELABS_BASE = "https://api.pricelabs.co/v1"
PRICELABS_HEADERS = {"X-API-Key": os.getenv("PRICELABS_API_KEY")}


# ── Hospitable ────────────────────────────────────────────────────────────────

def get_all_properties():
    r = requests.get(f"{HOSPITABLE_BASE}/properties", headers=HOSPITABLE_HEADERS, params={"per_page": 100})
    r.raise_for_status()
    return r.json().get("data", [])


def get_reservations_page(property_ids, page, per_page=100, start_date=None, end_date=None):
    params = [("properties[]", pid) for pid in property_ids]
    params += [
        ("page", page),
        ("per_page", per_page),
        ("include", "financials,guest,properties"),
        ("status[]", "accepted"),
    ]
    if start_date:
        params.append(("start_date", start_date))
    if end_date:
        params.append(("end_date", end_date))
    r = requests.get(f"{HOSPITABLE_BASE}/reservations", headers=HOSPITABLE_HEADERS, params=params)
    r.raise_for_status()
    return r.json()


def get_all_reservations(property_ids, start_date, end_date):
    all_reservations = []
    page = 1
    while True:
        data = get_reservations_page(property_ids, page, start_date=start_date, end_date=end_date)
        items = data.get("data", [])
        all_reservations.extend(items)
        meta = data.get("meta", {})
        current = meta.get("current_page", page)
        last = meta.get("last_page", 1)
        total = meta.get("total", len(all_reservations))
        print(f"  Page {current}/{last} — {len(items)} reservations (total so far: {len(all_reservations)}/{total})")
        if current >= last:
            break
        page += 1
    return all_reservations


# ── PriceLabs ─────────────────────────────────────────────────────────────────

def get_pricelabs_listings():
    r = requests.get(f"{PRICELABS_BASE}/listings", headers=PRICELABS_HEADERS)
    r.raise_for_status()
    return r.json().get("listings", [])


def match_pricelabs_to_hospitable(pl_listings, h_properties):
    """
    Match PriceLabs listings to Hospitable properties.
    Priority: UUID match (smartbnb pms) → name fuzzy match.
    Returns a dict: hospitable_property_id -> merged PriceLabs data (best match).
    """
    h_by_id = {p["id"]: p for p in h_properties}
    h_by_name = {p["name"].lower().strip(): p["id"] for p in h_properties}

    matched = {}  # hospitable_id -> list of pl listings

    for pl in pl_listings:
        pid = pl["id"]
        h_id = None

        # Direct UUID match (smartbnb pms uses Hospitable UUIDs as IDs)
        if pid in h_by_id:
            h_id = pid
        else:
            # Name-based match
            pl_name = pl.get("name", "").lower().strip()
            for h_name, hid in h_by_name.items():
                # Simple substring match
                if pl_name and (pl_name in h_name or h_name in pl_name):
                    h_id = hid
                    break

        if h_id:
            matched.setdefault(h_id, []).append(pl)

    # For each hospitable property, prefer the smartbnb/UUID entry if multiple matches
    result = {}
    for h_id, pl_list in matched.items():
        uuid_matches = [l for l in pl_list if l["id"] == h_id]
        result[h_id] = uuid_matches[0] if uuid_matches else pl_list[0]

    return result


# ── Management Fees ───────────────────────────────────────────────────────────

def load_management_fees(path="management_fees.csv"):
    fees = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["property_id"] and row["mgmt_fee_value"]:
                fees[row["property_id"]] = {
                    "type": row["mgmt_fee_type"],
                    "value": float(row["mgmt_fee_value"]),
                }
    return fees


# ── Revenue Targets ───────────────────────────────────────────────────────────

def load_revenue_targets(path="revenue_targets.csv"):
    import re
    targets = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            pid = row.get("property_id", "").strip()
            mn  = row.get("month_num", "").strip()
            if not pid or not mn:
                continue
            def clean(v):
                v = re.sub(r"[^0-9.]", "", v or "")
                return float(v) if v else None
            rev_t = clean(row.get("revenue_target", ""))
            occ_t = clean(row.get("occupancy_target_pct", ""))
            closed = (rev_t is None or rev_t == 0) and (occ_t is None or occ_t == 0)
            if pid not in targets:
                targets[pid] = {}
            targets[pid][int(mn)] = {
                "revenue_target":   None if closed else rev_t,
                "occupancy_target": None if closed else occ_t,
                "closed":           closed,
            }
    return targets


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("── Hospitable ──────────────────────────────")
    print("Fetching properties...")
    properties = get_all_properties()
    property_ids = [p["id"] for p in properties]
    print(f"Found {len(properties)} properties\n")

    start_date = "2024-01-01"
    end_date = "2026-12-31"
    print(f"Fetching reservations {start_date} → {end_date}...")
    reservations = get_all_reservations(property_ids, start_date, end_date)
    print(f"Total accepted reservations fetched: {len(reservations)}")
    reservations = [
        r for r in reservations
        if (((r.get("financials") or {}).get("host") or {}).get("revenue") or {}).get("amount", 0) > 0
    ]
    print(f"Confirmed revenue reservations (amount > $0): {len(reservations)}\n")

    print("── PriceLabs ───────────────────────────────")
    print("Fetching PriceLabs listings...")
    pl_listings = get_pricelabs_listings()
    print(f"Found {len(pl_listings)} PriceLabs listings")

    pl_matched = match_pricelabs_to_hospitable(pl_listings, properties)
    print(f"Matched {len(pl_matched)}/{len(properties)} Hospitable properties to PriceLabs\n")

    for p in properties:
        tag = "✓" if p["id"] in pl_matched else "✗"
        print(f"  {tag} {p['name']}")

    print("\n── Management Fees ─────────────────────────────────")
    mgmt_fees = load_management_fees()
    print(f"Loaded {len(mgmt_fees)} management fee entries")

    print("\n── Revenue Targets ─────────────────────────────────")
    revenue_targets = load_revenue_targets()
    open_months  = sum(1 for p in revenue_targets.values() for m in p.values() if not m["closed"])
    closed_months = sum(1 for p in revenue_targets.values() for m in p.values() if m["closed"])
    print(f"Loaded targets for {len(revenue_targets)} properties — {open_months} open months, {closed_months} closed months")

    output = {
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "properties": properties,
        "reservations": reservations,
        "pricelabs_listings": pl_listings,
        "pricelabs_matched": pl_matched,
        "management_fees": mgmt_fees,
        "revenue_targets": revenue_targets,
        "annual_targets": {"2026": 2300000},
    }
    with open("data.json", "w") as f:
        json.dump(output, f, indent=2)
    print("\nSaved to data.json")
