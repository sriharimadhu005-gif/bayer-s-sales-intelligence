"""
Horeca Sales Intelligence — Intelligent Entity Resolution & Clarification Pipeline

Pipeline:
1. Pending Clarification Check:
   If the user is answering a previous disambiguation question (e.g. "RPC Layout" or "2"),
   resolve the selection, merge with the original query, and clear the pending state.
2. Entity & Intent Extraction:
   Extract candidate mentions: Customer/Business, Product/SKU, Route, Location, Date.
3. Alias Lookup & Fuzzy Matching:
   Use PostgreSQL pg_trgm trigram similarity, ILIKE, normalized string matching,
   and alias dictionaries (sku_alias_map).
4. Confidence Evaluation:
   - High Confidence (Single Match): Bind canonical entity IDs & names.
   - Ambiguous (Multiple Matches): Formulate numbered clarification question,
     save pending_clarification in conversation memory, and halt SQL generation.
   - Low Confidence (No matches): Formulate helpful guidance asking for location/route.
5. Grounded Injection:
   Provide resolved canonical entities to the SQL generator so queries never hallucinate.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from . import db


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    LOW_CONFIDENCE = "low_confidence"
    NONE_DETECTED = "none_detected"


@dataclass
class EntityResolutionResult:
    status: ResolutionStatus
    resolved_customer: dict[str, Any] | None = None
    resolved_sku: dict[str, Any] | None = None
    resolved_route: int | None = None
    resolved_location: str | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
    clarification_text: str | None = None
    clarification_state: dict[str, Any] | None = None
    extracted_mentions: dict[str, Any] = field(default_factory=dict)
    augmented_message: str | None = None


# Common business noise suffixes to strip for normalized root comparison
BUSINESS_SUFFIXES = [
    r"\bllp\b", r"\bpvt\b", r"\bltd\b", r"\bprivate\b", r"\blimited\b",
    r"\benterprises?\b", r"\brestaurants?\b", r"\bhotels?\b", r"\bcaterers?\b",
    r"\bcondiments?\b", r"\bco\b", r"\bcorp\b", r"\bcorporation\b",
    r"\bservices?\b", r"\bvegs?\b", r"\bfast\s+food\b", r"\b\(pl\)\b",
    r"\b\(hotel\s+special\)\b", r"\b\(spl\)\b", r"\b\(e\)\b"
]

COMMON_LOCATIONS = [
    "vijayanagar", "rpc layout", "basaveshwaranagar", "sheshadripuram",
    "jayanagar", "jp nagar", "btm", "frezer town", "frazer town",
    "lingrajpura", "rajajinagar", "uttarahalli", "indiranagar", "mg road",
    "malleswaram", "koramangala", "yelahanka", "tumkur", "kadubeesanahalli",
    "basavanagudi", "southend circle", "r t nagar", "rt nagar", "k j road"
]


def normalize_text(text: str) -> str:
    """Lowercase and strip special characters, redundant spaces."""
    if not text:
        return ""
    s = text.lower().strip()
    s = re.sub(r"[^\w\s\-]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_business_name(name: str) -> str:
    """Normalize business name by removing corporate/store suffixes for root matching."""
    s = normalize_text(name)
    for pat in BUSINESS_SUFFIXES:
        s = re.sub(pat, " ", s, flags=re.IGNORECASE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ═══════════════════════════════════════════════════════════════════════
# STEP 1: ENTITY EXTRACTION
# ═══════════════════════════════════════════════════════════════════════

def extract_candidate_mentions(message: str) -> dict[str, Any]:
    """
    Extract entity candidates from natural language text.
    Extracts:
    - customer_mention
    - customer_id_mention
    - sku_mention
    - route_mention
    - location_mention
    """
    msg = message.strip()
    norm_msg = normalize_text(msg)
    extracted: dict[str, Any] = {}

    # 1. Direct Customer ID pattern: e.g. A292, C1666, B428, H703
    id_match = re.search(r"\b([A-Z]\d{2,5})\b", msg)
    if id_match:
        extracted["customer_id_mention"] = id_match.group(1)

    # 2. Route mention: e.g. Route 1, R1, Route 3
    route_match = re.search(r"\b(?:route|r)\s*([1-7])\b", norm_msg)
    if route_match:
        extracted["route_mention"] = int(route_match.group(1))

    # 3. Location mention
    for loc in COMMON_LOCATIONS:
        if loc in norm_msg:
            extracted["location_mention"] = loc
            break

    # 4. Customer Name extraction patterns
    cust_patterns = [
        r"(?:customer|client|dealer|buyer)\s+([A-Za-z0-9\s\-\'\&]{3,45})",
        r"(?:what did|how much did|items)\s+([A-Za-z0-9\s\-\'\&]{3,45})\s+(?:buy|bought|purchase|ordered|order|pay)",
        r"(?:rate for|price for|std rate for|balance for|balance of)\s+([A-Za-z0-9\s\-\'\&]{3,45})",
        r"(?:account of|ledger of)\s+([A-Za-z0-9\s\-\'\&]{3,45})",
        r"(?:for|to)\s+([A-Za-z0-9\s\-\'\&]{3,45})",
    ]
    date_and_noise_words = {
        "coffee", "tea", "december", "april", "march", "january", "february", "may",
        "june", "july", "august", "september", "october", "november", "all", "all routes",
        "route", "routes", "today", "yesterday", "tomorrow", "this week", "last week",
        "this month", "last month", "sale", "sales", "price", "rate", "cost", "total",
        "kg", "kgs", "quantity", "volume", "all the routes", "all routes combined"
    }
    for pat in cust_patterns:
        m = re.search(pat, msg, re.IGNORECASE)
        if m:
            mention = m.group(1).strip()
            # Clean trailing prepositions/keywords
            mention = re.sub(r"\b(in|at|on|for|with|of|bought|during|between|from|to)\b.*$", "", mention, flags=re.IGNORECASE).strip()
            # Check that mention does not contain date numbers or month names
            contains_date = any(month in mention.lower() for month in [
                "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"
            ]) or bool(re.search(r"\b\d{1,2}(?:st|nd|rd|th)?\b|\b\d{4}\b", mention))
            if mention and len(mention) >= 3 and not mention.isdigit() and not contains_date and mention.lower() not in date_and_noise_words:
                extracted["customer_mention"] = mention
                break

    # 5. SKU extraction patterns (only capture specific product names, not the generic categories 'coffee' or 'tea')
    sku_patterns = [
        r"\b(coffee[\-\s]+[A-Za-z0-9\(\)]+[\w\s\-\(\)]*?)(?:\s+(?:for|in|from|at|on)|\?|$)",
        r"\b(tea[\-\s]+[A-Za-z0-9\(\)]+[\w\s\-\(\)]*?)(?:\s+(?:for|in|from|at|on)|\?|$)",
        r"\b(pure coffee[\w\s\-\(\)]*?)(?:\s+(?:for|in|from|at|on)|\?|$)",
        r"\b(badam powder[\w\s\-\(\)]*?)(?:\s+(?:for|in|from|at|on)|\?|$)",
        r"\b(coca\s*cola|coke|diet coke)\b",
        r"\b(frappe sauce[\w\s]*)\b",
    ]
    for pat in sku_patterns:
        m = re.search(pat, msg, re.IGNORECASE)
        if m:
            candidate_sku = m.group(1).strip()
            candidate_sku_clean = re.sub(r"\b(in|at|on|for|with|of|from|to)\b.*$", "", candidate_sku, flags=re.IGNORECASE).strip()
            if candidate_sku_clean.lower() not in ["coffee", "tea", "pure coffee", "all", "total"]:
                extracted["sku_mention"] = candidate_sku_clean
            elif candidate_sku_clean.lower() == "pure coffee":
                extracted["sku_mention"] = candidate_sku_clean
            break

    # 5.1 Check known SKU product names and roots (e.g. classic, atrium, supreme, etc.)
    known_sku_names = [
        "classic blend", "classic", "atrium", "brownie special", "cafe supreme", "supreme",
        "hotel special", "daily roast", "super shakthi", "special gold", "kt royal",
        "kt gold", "kt citizen", "prakash tea", "badam powder", "pure coffee", "80 degree",
        "french roast", "city roast", "mysore blend", "arabica", "robusta"
    ]
    if "sku_mention" not in extracted:
        for kn in known_sku_names:
            if re.search(rf"\b{re.escape(kn)}\b", norm_msg):
                extracted["sku_mention"] = kn
                break

    # If customer_mention mistakenly captured an SKU name, clear it
    if "customer_mention" in extracted and "sku_mention" in extracted:
        c_norm = normalize_text(extracted["customer_mention"])
        s_norm = normalize_text(extracted["sku_mention"])
        if c_norm == s_norm or s_norm in c_norm:
            del extracted["customer_mention"]

    # 6. Extract pack size if present (e.g. 100g, 200g, 250g, 500g, 1000g, 200, 500)
    size_match = re.search(r"\b(\d{2,4})\s*(?:g|gm|gms|ml|kg)?\b", msg, re.IGNORECASE)
    if size_match:
        sz = int(size_match.group(1))
        if sz in [50, 65, 70, 75, 100, 110, 150, 200, 250, 320, 350, 400, 500, 600, 1000, 5000]:
            extracted["pack_size"] = str(sz)

    # 7. Extract blend ratio if present (e.g. 80/20, 70/30, 85/15)
    blend_match = re.search(r"\b(80/20|70/30|85/15|60/40|65/35)\b", norm_msg)
    if blend_match:
        extracted["blend_ratio"] = blend_match.group(1)

    # 8. Check common SKU abbreviations and short codes
    alias_codes = [
        "bs (90/10)", "bs 90/10", "bt special 250", "daily roast 500", "delight 1000ml",
        "super shakthi 500", "super shakthi", "special gold 500g", "special gold",
        "kt royal", "kt gold", "kt citizen", "prakash tea", "bs", "bc", "80d", "mr",
        "at", "spc", "spt", "pt", "smt", "gl", "kt", "shakthi", "pure", "delight", "chicory", "coke"
    ]
    for code in alias_codes:
        if re.search(rf"\b{re.escape(code)}\b", norm_msg):
            extracted["sku_alias"] = code
            break

    return extracted


# ═══════════════════════════════════════════════════════════════════════
# STEP 2 & 7: FUZZY ENTITY MATCHING & ALIAS LOOKUP
# ═══════════════════════════════════════════════════════════════════════

def match_customer(
    mention: str | None,
    customer_id: str | None = None,
    location_hint: str | None = None,
    route_hint: int | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """
    Search for customers in PostgreSQL following 4-tier authoritative priority:
    1. customer_master exact customer_id or customer_name match
    2. customer_master normalized name / pg_trgm / ILIKE matching
    3. Fallback to existing customers and rate_cards
    4. Otherwise empty candidates list
    """
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    # 1. Exact ID match (Tier 1: customer_master first)
    if customer_id:
        master_id_rows = db.query(
            "SELECT customer_id, customer_name AS name, address, route_number, tally_id FROM customer_master WHERE customer_id ILIKE %s",
            [customer_id]
        )
        for r in master_id_rows:
            return [{
                "customer_id": r["customer_id"],
                "name": r["name"],
                "address": r.get("address"),
                "route_number": r.get("route_number"),
                "tally_id": r.get("tally_id"),
                "similarity": 1.0,
                "match_type": "exact_id",
            }]

        # Fallback to customers table for exact ID
        rows = db.query(
            "SELECT customer_id, name, address, route_number FROM customers WHERE customer_id ILIKE %s",
            [customer_id]
        )
        for r in rows:
            return [{
                "customer_id": r["customer_id"],
                "name": r["name"],
                "address": r.get("address"),
                "route_number": r.get("route_number"),
                "similarity": 1.0,
                "match_type": "exact_id",
            }]

    if not mention:
        return []

    mention_norm = normalize_text(mention)
    root_mention = normalize_business_name(mention)
    like_pattern = f"%{mention_norm}%"
    loc_pattern = f"%{normalize_text(location_hint)}%" if location_hint else like_pattern

    # 2. Search authoritative customer_master first (Tier 1 & 2)
    master_sql = """
        SELECT 
            customer_id, 
            customer_name AS name, 
            address, 
            route_number,
            tally_id,
            similarity(LOWER(customer_name), LOWER(%s)) AS sim
        FROM customer_master
        WHERE 
            customer_name ILIKE %s
            OR normalized_name = %s
            OR normalized_name ILIKE %s
            OR similarity(LOWER(customer_name), LOWER(%s)) > 0.3
            OR (address IS NOT NULL AND address ILIKE %s)
        ORDER BY 
            ((address IS NOT NULL AND address ILIKE %s) OR customer_name ILIKE %s) DESC,
            (customer_name ILIKE %s) DESC,
            sim DESC,
            customer_name
        LIMIT %s
    """
    master_rows = db.query(master_sql, [
        mention_norm, mention_norm, mention_norm, like_pattern, mention_norm, loc_pattern,
        loc_pattern, loc_pattern, mention_norm, limit * 3
    ])

    for r in master_rows:
        cid = r["customer_id"]
        if cid in seen_ids:
            continue
        seen_ids.add(cid)

        sim = float(r.get("sim") or 0.0)
        cname_norm = normalize_text(r["name"])
        croot_norm = normalize_business_name(r["name"])

        # Boost score if exact name
        if cname_norm == mention_norm:
            sim = 1.0
        elif root_mention and root_mention == croot_norm:
            sim = max(sim, 0.95)
        elif root_mention and root_mention in croot_norm:
            sim = max(sim, 0.85)

        # Boost score if user location hint matches address
        if location_hint and r.get("address") and location_hint in normalize_text(r["address"]):
            sim = min(1.0, sim + 0.15)

        # Boost score if route hint matches
        if route_hint is not None and r.get("route_number") == route_hint:
            sim = min(1.0, sim + 0.10)

        candidates.append({
            "customer_id": cid,
            "name": r["name"],
            "address": r.get("address") or "",
            "route_number": r.get("route_number"),
            "tally_id": r.get("tally_id"),
            "similarity": round(sim, 3),
            "match_type": "customer_master",
        })

    # 3. Fallback to customers & rate_cards if no customer_master candidates found (Tier 3)
    if not candidates:
        sql = """
            SELECT 
                customer_id, 
                name, 
                address, 
                route_number,
                similarity(LOWER(name), LOWER(%s)) AS sim
            FROM customers
            WHERE 
                name ILIKE %s
                OR name ILIKE %s
                OR similarity(LOWER(name), LOWER(%s)) > 0.3
                OR (address IS NOT NULL AND address ILIKE %s)
            ORDER BY 
                ((address IS NOT NULL AND address ILIKE %s) OR name ILIKE %s) DESC,
                (name ILIKE %s) DESC,
                sim DESC,
                name
            LIMIT %s
        """
        rows = db.query(sql, [
            mention_norm, mention_norm, like_pattern, mention_norm, loc_pattern,
            loc_pattern, loc_pattern, mention_norm, limit * 3
        ])

        for r in rows:
            cid = r["customer_id"]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)

            sim = float(r.get("sim") or 0.0)
            cname_norm = normalize_text(r["name"])
            croot_norm = normalize_business_name(r["name"])

            if root_mention and root_mention == croot_norm:
                sim = max(sim, 0.95)
            elif root_mention and root_mention in croot_norm:
                sim = max(sim, 0.85)

            if location_hint and r.get("address") and location_hint in normalize_text(r["address"]):
                sim = min(1.0, sim + 0.15)

            if route_hint is not None and r.get("route_number") == route_hint:
                sim = min(1.0, sim + 0.10)

            candidates.append({
                "customer_id": cid,
                "name": r["name"],
                "address": r.get("address") or "",
                "route_number": r.get("route_number"),
                "similarity": round(sim, 3),
                "match_type": "trgm_ilike",
            })

    # If still no candidates found, search rate_cards sub_group / customer_name
    if not candidates:
        rc_sql = """
            SELECT DISTINCT
                rc.customer_id,
                rc.customer_name AS name,
                c.address,
                c.route_number,
                rc.code AS tally_id,
                similarity(LOWER(rc.customer_name), LOWER(%s)) AS sim
            FROM rate_cards rc
            LEFT JOIN customers c ON rc.customer_id = c.customer_id
            WHERE 
                rc.customer_id IS NOT NULL
                AND (
                    similarity(LOWER(rc.customer_name), LOWER(%s)) > 0.3
                    OR rc.customer_name ILIKE %s
                    OR (rc.sub_group IS NOT NULL AND rc.sub_group ILIKE %s)
                )
            ORDER BY sim DESC
            LIMIT %s
        """
        rc_rows = db.query(rc_sql, [mention_norm, mention_norm, like_pattern, like_pattern, limit])
        for r in rc_rows:
            cid = r["customer_id"]
            if cid in seen_ids:
                continue
            seen_ids.add(cid)
            candidates.append({
                "customer_id": cid,
                "name": r["name"],
                "address": r.get("address") or "",
                "route_number": r.get("route_number"),
                "tally_id": r.get("tally_id"),
                "similarity": round(float(r.get("sim") or 0.6), 3),
                "match_type": "rate_card_alias",
            })

    # Sort descending by similarity
    candidates.sort(key=lambda x: x["similarity"], reverse=True)
    return candidates[:limit]


def match_sku(
    mention: str | None, 
    alias: str | None = None, 
    pack_size: str | None = None
) -> list[dict[str, Any]]:
    """
    Search for SKUs in standard_rate_cards, sku_alias_map, and sku_family_master.
    If alias maps to multiple pack sizes / variants, returns all variants unless pack_size narrows it.
    """
    candidates: list[dict[str, Any]] = []

    lookup_term = alias or mention
    if lookup_term:
        alias_rows = db.query(
            """
            SELECT sam.sales_sku_name, sam.rate_card_sku_name, sfm.product_name, sfm.main_group, sfm.blend_ratio
            FROM sku_alias_map sam
            LEFT JOIN sku_family_master sfm ON sam.family_id = sfm.id
            WHERE sam.sales_sku_name ILIKE %s OR sfm.product_code ILIKE %s
            """,
            [lookup_term.strip(), lookup_term.strip()]
        )
        if alias_rows:
            canonical_name = alias_rows[0]["rate_card_sku_name"]
            product_name = alias_rows[0].get("product_name") or ""
            
            # Extract clean keyword to find all pack-size variants in standard_rate_cards
            core_name = re.sub(r"-\d+$", "", canonical_name)
            core_name = re.sub(r"\s*\([^\)]*\)$", "", core_name)
            core_clean = core_name.split("-")[-1].strip()

            std_rows = db.query(
                """
                SELECT sku_name, category, uom, std_rate 
                FROM standard_rate_cards 
                WHERE sku_name ILIKE %s
                ORDER BY (sku_name ILIKE %s) DESC, sku_name
                """,
                [f"%{core_clean}%", canonical_name]
            )
            
            if std_rows:
                all_variants = [{
                    "sku_name": r["sku_name"],
                    "category": r.get("category"),
                    "uom": r.get("uom"),
                    "std_rate": float(r["std_rate"]) if r.get("std_rate") is not None else None,
                    "similarity": 1.0,
                    "match_type": "alias_exact",
                    "product_name": product_name,
                } for r in std_rows]
                
                # If user specified a pack size (e.g. 200, 500), filter to it
                if pack_size:
                    filtered = [v for v in all_variants if f"-{pack_size}" in v["sku_name"] or f" {pack_size}" in v["sku_name"]]
                    if filtered:
                        return filtered
                
                return all_variants

    if not mention:
        return []

    norm_mention = normalize_text(mention)
    like_pat = f"%{norm_mention}%"

    # Query standard_rate_cards using pg_trgm + ILIKE
    sql = """
        SELECT 
            sku_name, 
            category, 
            uom, 
            std_rate, 
            similarity(LOWER(sku_name), LOWER(%s)) AS sim
        FROM standard_rate_cards
        WHERE 
            sku_name ILIKE %s
            OR sku_name ILIKE %s
            OR similarity(LOWER(sku_name), LOWER(%s)) > 0.3
        ORDER BY 
            (sku_name ILIKE %s) DESC,
            sim DESC,
            sku_name
        LIMIT 5
    """
    rows = db.query(sql, [norm_mention, norm_mention, like_pat, norm_mention, norm_mention])
    for r in rows:
        sim = float(r.get("sim") or 0.0)
        candidates.append({
            "sku_name": r["sku_name"],
            "category": r.get("category"),
            "uom": r.get("uom"),
            "std_rate": float(r["std_rate"]) if r.get("std_rate") is not None else None,
            "similarity": round(sim, 3),
            "match_type": "std_trgm",
        })

    return candidates


# ═══════════════════════════════════════════════════════════════════════
# STEP 3 & 4: CONFIDENCE EVALUATION & DISAMBIGUATION
# ═══════════════════════════════════════════════════════════════════════

def evaluate_resolution(
    message: str,
    extracted: dict[str, Any],
) -> EntityResolutionResult:
    """
    Evaluate candidate entities and determine whether to proceed, clarify,
    or ask for more details.
    """
    customer_mention = extracted.get("customer_mention")
    customer_id_mention = extracted.get("customer_id_mention")
    location_hint = extracted.get("location_mention")
    route_hint = extracted.get("route_mention")
    sku_mention = extracted.get("sku_mention")
    sku_alias = extracted.get("sku_alias")
    pack_size = extracted.get("pack_size")

    resolved_customer = None
    resolved_sku = None

    # --- Match Customer if present ---
    if customer_mention or customer_id_mention:
        candidates = match_customer(
            mention=customer_mention,
            customer_id=customer_id_mention,
            location_hint=location_hint,
            route_hint=route_hint,
        )

        # Case 1: Exhaustive search found 0 candidates or lowest confidence
        if not candidates or (candidates[0]["similarity"] < 0.35 and candidates[0]["match_type"] != "exact_id"):
            clarification_text = (
                f"I couldn't confidently identify the customer **'{customer_mention or customer_id_mention}'**.\n\n"
                "Could you provide a little more information such as their branch location, route number, "
                "or the full registered name?"
            )
            return EntityResolutionResult(
                status=ResolutionStatus.LOW_CONFIDENCE,
                clarification_text=clarification_text,
                extracted_mentions=extracted,
            )

        # Case 2: Exactly ONE high-confidence candidate
        top = candidates[0]
        if len(candidates) == 1:
            resolved_customer = top
        elif top["similarity"] >= 0.95 and (len(candidates) == 1 or top["similarity"] - candidates[1]["similarity"] >= 0.25):
            resolved_customer = top
        elif top["match_type"] == "exact_id":
            resolved_customer = top
        else:
            # Case 3: MULTIPLE reasonable candidates exist -> AMBIGUITY
            # Pick diverse candidates (at most 2 with identical name, so variants like 'RPC Layout' and 'New Shanthi Sagar' are included)
            options_to_present = []
            name_counts: dict[str, int] = {}
            for c in candidates:
                cname = c["name"].lower()
                if name_counts.get(cname, 0) < 2:
                    options_to_present.append(c)
                    name_counts[cname] = name_counts.get(cname, 0) + 1
                if len(options_to_present) >= 4:
                    break
            if not options_to_present:
                options_to_present = candidates[:4]

            lines = [
                f"I found multiple customers matching **'{customer_mention}'**. Which one did you mean?\n"
            ]
            for idx, c in enumerate(options_to_present, 1):
                route_str = f"Route {c['route_number']}" if c.get("route_number") else "Route N/A"
                addr_str = f", {c['address'].title()}" if c.get("address") else ""
                lines.append(f"{idx}. **{c['name'].title()}** ({route_str}{addr_str})")

            lines.append("\nPlease reply with the number or branch name.")
            clarification_text = "\n".join(lines)

            clarification_state = {
                "entity_type": "customer",
                "mention": customer_mention,
                "original_message": message,
                "candidates": options_to_present,
                "extracted": extracted,
            }

            return EntityResolutionResult(
                status=ResolutionStatus.AMBIGUOUS,
                candidates=options_to_present,
                clarification_text=clarification_text,
                clarification_state=clarification_state,
                extracted_mentions=extracted,
            )

    # --- Match SKU if present ---
    if sku_mention or sku_alias:
        sku_candidates = match_sku(sku_mention, sku_alias, pack_size=pack_size)
        if len(sku_candidates) == 1:
            resolved_sku = sku_candidates[0]
        elif len(sku_candidates) > 1:
            # If user specified a pack size, filter by pack size
            if pack_size:
                filtered_pack = [
                    v for v in sku_candidates 
                    if f"-{pack_size}" in v["sku_name"] or f" {pack_size}" in v["sku_name"] or f"({pack_size})" in v["sku_name"]
                ]
                if len(filtered_pack) == 1:
                    resolved_sku = filtered_pack[0]

            if not resolved_sku and not resolved_customer:
                # Intent-aware entity resolution:
                # Do NOT trigger clarification if the query has comparison, ranking,
                # superlative, or variant performance inquiry intent.
                from . import intent_planner
                if intent_planner.is_comparison_intent(message):
                    return EntityResolutionResult(
                        status=ResolutionStatus.RESOLVED,
                        resolved_sku=sku_candidates[0],
                        candidates=sku_candidates,
                        extracted_mentions=extracted,
                    )

                mention_disp = (sku_mention or sku_alias or "the requested product").strip().title()
                def _fmt_sku_opt(name: str) -> str:
                    parts = name.split("-")
                    if len(parts) == 3 and parts[2].isdigit():
                        return f"{parts[1]} {parts[2]} g"
                    if len(parts) == 2 and parts[1].isdigit():
                        return f"{parts[0]} {parts[1]} g"
                    return name

                clean_opts = [_fmt_sku_opt(sc["sku_name"]) for sc in sku_candidates[:4]]
                if len(clean_opts) == 2:
                    opts_text = f"{clean_opts[0]} or {clean_opts[1]}"
                else:
                    opts_text = ", ".join(clean_opts[:-1]) + f", or {clean_opts[-1]}"

                clarification_text = f"I found multiple SKUs matching '{mention_disp}'. Which one do you mean: {opts_text}?"
                lines = [
                    f"I found multiple SKUs matching **'{mention_disp}'**. Which one do you mean:\n"
                ]
                for idx, sc in enumerate(sku_candidates[:5], 1):
                    rate_str = f" (Std Rate: Rs.{sc['std_rate']:.2f}/kg)" if sc.get("std_rate") is not None else ""
                    lines.append(f"{idx}. **{sc['sku_name']}**{rate_str}")
                lines.append("\nPlease reply with the option number or pack size.")
                clarification_state = {
                    "entity_type": "sku",
                    "alias": sku_alias or sku_mention,
                    "original_message": message,
                    "candidates": sku_candidates[:5],
                    "extracted": extracted,
                }
                return EntityResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS,
                    candidates=sku_candidates[:5],
                    clarification_text=clarification_text,
                    clarification_state=clarification_state,
                    extracted_mentions=extracted,
                )
            elif not resolved_sku:
                resolved_sku = sku_candidates[0]

    # If neither customer nor SKU had ambiguity, return RESOLVED or NONE_DETECTED
    if resolved_customer or resolved_sku or route_hint is not None:
        return EntityResolutionResult(
            status=ResolutionStatus.RESOLVED,
            resolved_customer=resolved_customer,
            resolved_sku=resolved_sku,
            resolved_route=route_hint,
            resolved_location=location_hint,
            extracted_mentions=extracted,
        )

    return EntityResolutionResult(
        status=ResolutionStatus.NONE_DETECTED,
        extracted_mentions=extracted,
    )


# ═══════════════════════════════════════════════════════════════════════
# STEP 6: CONVERSATIONAL MEMORY & CLARIFICATION RESOLVER
# ═══════════════════════════════════════════════════════════════════════

def resolve_clarification_reply(
    reply: str,
    pending_state: dict[str, Any],
) -> dict[str, Any] | None:
    """
    Resolve the user's reply to an earlier clarification question (Customer or SKU).
    Supports:
    - Numeric answers: "1", "2", "3", "#2"
    - Ordinals: "first", "1st", "second", "2nd", "third", "3rd"
    - Pack sizes (for SKU): "200", "200g", "500", "500g"
    - Partial branch/address name (for Customer): "RPC Layout", "Basaveshwaranagar"
    """
    candidates = pending_state.get("candidates", [])
    if not candidates:
        return None

    norm_reply = normalize_text(reply)
    entity_type = pending_state.get("entity_type", "customer")

    # 1. Handle SKU Clarification specifically
    if entity_type == "sku":
        # Check pack size match in reply (e.g. "200", "200g", "500", "500g", "250g")
        sizes = re.findall(r"(\d{2,4})\s*(?:g|gm|gms|ml|kg)?", reply, re.IGNORECASE)
        if sizes:
            for sz in sizes:
                for c in candidates:
                    c_name = c.get("sku_name", "")
                    if f"-{sz}" in c_name or f" {sz}" in c_name:
                        return c

        # Check explicit option number: "1", "#1", "option 1", "1. Cafe Supreme", "first"
        opt_match = re.search(r"^(?:option\s*|#)?(\d{1,2})(?:[\.\:\-\s]|$)", norm_reply.strip())
        if opt_match:
            idx = int(opt_match.group(1)) - 1
            if 0 <= idx < len(candidates):
                return candidates[idx]

        ordinals = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4}
        for word, idx in ordinals.items():
            if word in norm_reply and idx < len(candidates):
                return candidates[idx]

        # Check substring match in sku_name
        for c in candidates:
            if norm_reply in c.get("sku_name", "").lower():
                return c
        return None

    # 2. Handle Customer Clarification
    # Numeric match: "1", "2", "#1", "option 1", "1. Shanthi Sagar"
    num_match = re.search(r"^(?:option\s*|#)?(\d{1,2})(?:[\.\:\-\s]|$)", norm_reply.strip())
    if num_match:
        idx = int(num_match.group(1)) - 1
        if 0 <= idx < len(candidates):
            return candidates[idx]

    # Ordinal words
    ordinals = {
        "first": 0, "1st": 0,
        "second": 1, "2nd": 1,
        "third": 2, "3rd": 2,
        "fourth": 3, "4th": 3,
        "fifth": 4, "5th": 4,
    }
    for word, idx in ordinals.items():
        if word in norm_reply and idx < len(candidates):
            return candidates[idx]

    # 4. Handle Customer Clarification
    # Substring match against candidate name or address
    for c in candidates:
        cname = normalize_text(c.get("name", ""))
        caddr = normalize_text(c.get("address") or "")
        cid = normalize_text(c.get("customer_id") or "")

        if norm_reply in cname or norm_reply in caddr or norm_reply == cid:
            return c

    # Customer token overlap match
    reply_tokens = set(norm_reply.split())
    best_match = None
    best_overlap = 0

    for c in candidates:
        ctoks = set(normalize_text(c.get("name", "")).split()) | set(normalize_text(c.get("address") or "").split())
        overlap = len(reply_tokens.intersection(ctoks))
        if overlap > best_overlap:
            best_overlap = overlap
            best_match = c

    if best_overlap > 0:
        return best_match

    # Fallback: Re-match customer with original mention + user reply as location/name hint
    orig_mention = pending_state.get("mention", "")
    if orig_mention:
        rerun_loc = match_customer(orig_mention, location_hint=norm_reply, limit=1)
        if rerun_loc and rerun_loc[0]["similarity"] >= 0.7:
            return rerun_loc[0]
        rerun_comb = match_customer(f"{orig_mention} {reply}", limit=1)
        if rerun_comb and rerun_comb[0]["similarity"] >= 0.7:
            return rerun_comb[0]

    return None
