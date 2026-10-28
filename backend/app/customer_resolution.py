"""
Customer ID & Entity Resolution Service.

Implements the authoritative 4-tier Customer-ID resolution priority:
  Tier 1: `customer_master` exact customer-ID / customer-name match
  Tier 2: `customer_master` normalized-name match, only if unambiguous
  Tier 3: Existing price-sheet (`rate_cards`) customer ID as fallback
  Tier 4: Return "customer ID not found" without inventing a value

Also provides authoritative Tally-ID resolution:
  1. `customer_master.tally_id`
  2. Fallback to `rate_cards.code`
  3. Otherwise None
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from . import db


class CustomerResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


@dataclass
class ResolvedCustomer:
    customer_id: str | None
    customer_name: str | None
    normalized_name: str | None
    tally_id: str | None
    route_number: int | None
    address: str | None
    phone: str | None
    tier: int  # 1 = exact master, 2 = normalized master, 3 = price-sheet fallback, 4 = not found
    status: CustomerResolutionStatus
    candidates: list[dict[str, Any]] = field(default_factory=list)
    match_type: str = "none"
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "customer_id": self.customer_id,
            "customer_name": self.customer_name,
            "normalized_name": self.normalized_name,
            "tally_id": self.tally_id,
            "route_number": self.route_number,
            "address": self.address,
            "phone": self.phone,
            "tier": self.tier,
            "status": self.status.value,
            "match_type": self.match_type,
            "candidates": self.candidates,
            "message": self.message,
        }


def normalize_customer_name(name: str | None) -> str:
    """Normalize customer name by stripping punctuation, extra spaces, and lowercase."""
    if not name:
        return ""
    s = str(name).lower().strip()
    s = re.sub(r"[^\w\s\-]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def resolve_customer(
    identifier: str,
    location_hint: str | None = None,
    route_hint: int | None = None,
    limit: int = 5,
) -> ResolvedCustomer:
    """
    Resolve customer identifier or mention following strict 4-tier priority.

    Parameters
    ----------
    identifier : str
        Customer ID (e.g. 'C1666', 'C1382') or Customer Name mention.
    location_hint : str | None
        Optional location hint to disambiguate identical names across locations.
    route_hint : int | None
        Optional route number hint (1-7).
    limit : int
        Max candidate count for ambiguous matches.

    Returns
    -------
    ResolvedCustomer
        Resolved record with priority tier (1-4) and status.
    """
    if not identifier or not str(identifier).strip():
        return ResolvedCustomer(
            customer_id=None,
            customer_name=None,
            normalized_name=None,
            tally_id=None,
            route_number=None,
            address=None,
            phone=None,
            tier=4,
            status=CustomerResolutionStatus.NOT_FOUND,
            message="No identifier provided",
        )

    raw_input = str(identifier).strip()
    norm_input = normalize_customer_name(raw_input)

    # ═══════════════════════════════════════════════════════════════════
    # TIER 1: customer_master exact customer-ID / customer-name match
    # ═══════════════════════════════════════════════════════════════════

    # 1A. Exact Customer ID match in customer_master
    exact_id_rows = db.query(
        """
        SELECT 
            customer_id, customer_name, normalized_name, tally_id,
            route_number, phone, address
        FROM customer_master
        WHERE customer_id ILIKE %s
        LIMIT 1;
        """,
        [raw_input]
    )
    if exact_id_rows:
        r = exact_id_rows[0]
        return ResolvedCustomer(
            customer_id=r["customer_id"],
            customer_name=r["customer_name"],
            normalized_name=r["normalized_name"],
            tally_id=r["tally_id"],
            route_number=r["route_number"],
            address=r["address"],
            phone=r["phone"],
            tier=1,
            status=CustomerResolutionStatus.RESOLVED,
            match_type="master_exact_id",
        )

    # 1B. Exact Customer Name match in customer_master (case-insensitive exact)
    exact_name_rows = db.query(
        """
        SELECT 
            customer_id, customer_name, normalized_name, tally_id,
            route_number, phone, address
        FROM customer_master
        WHERE LOWER(customer_name) = LOWER(%s);
        """,
        [raw_input]
    )
    if exact_name_rows:
        if len(exact_name_rows) == 1:
            r = exact_name_rows[0]
            return ResolvedCustomer(
                customer_id=r["customer_id"],
                customer_name=r["customer_name"],
                normalized_name=r["normalized_name"],
                tally_id=r["tally_id"],
                route_number=r["route_number"],
                address=r["address"],
                phone=r["phone"],
                tier=1,
                status=CustomerResolutionStatus.RESOLVED,
                match_type="master_exact_name",
            )
        else:
            # Multiple distinct Customer IDs share the exact same name!
            # (e.g. 'sri vishnu park' -> C1382 and C1559)
            # Check if location_hint or route_hint can unambiguously pick one
            filtered = exact_name_rows
            if route_hint is not None:
                filtered = [r for r in filtered if r.get("route_number") == route_hint]
            if location_hint:
                norm_loc = normalize_customer_name(location_hint)
                filtered = [r for r in filtered if r.get("address") and norm_loc in normalize_customer_name(r["address"])]

            if len(filtered) == 1:
                r = filtered[0]
                return ResolvedCustomer(
                    customer_id=r["customer_id"],
                    customer_name=r["customer_name"],
                    normalized_name=r["normalized_name"],
                    tally_id=r["tally_id"],
                    route_number=r["route_number"],
                    address=r["address"],
                    phone=r["phone"],
                    tier=1,
                    status=CustomerResolutionStatus.RESOLVED,
                    match_type="master_exact_name_disambiguated",
                )

            # Ambiguous: Keep them distinct and make lookup ambiguity explicit
            candidates = [
                {
                    "customer_id": r["customer_id"],
                    "name": r["customer_name"],
                    "address": r.get("address") or "",
                    "route_number": r.get("route_number"),
                    "tally_id": r.get("tally_id"),
                }
                for r in exact_name_rows
            ]
            return ResolvedCustomer(
                customer_id=None,
                customer_name=raw_input,
                normalized_name=norm_input,
                tally_id=None,
                route_number=None,
                address=None,
                phone=None,
                tier=1,
                status=CustomerResolutionStatus.AMBIGUOUS,
                candidates=candidates,
                match_type="master_exact_name_ambiguous",
                message=f"Ambiguous: Name '{raw_input}' maps to {len(exact_name_rows)} distinct customer IDs",
            )

    # ═══════════════════════════════════════════════════════════════════
    # TIER 2: customer_master normalized-name match (only if unambiguous)
    # ═══════════════════════════════════════════════════════════════════
    # First check normalized_name exact match
    norm_rows = db.query(
        """
        SELECT 
            customer_id, customer_name, normalized_name, tally_id,
            route_number, phone, address
        FROM customer_master
        WHERE normalized_name = %s;
        """,
        [norm_input]
    )

    if not norm_rows:
        # Check pg_trgm similarity or substring ILIKE
        like_pattern = f"%{norm_input}%"
        norm_rows = db.query(
            """
            SELECT 
                customer_id, customer_name, normalized_name, tally_id,
                route_number, phone, address,
                similarity(LOWER(customer_name), LOWER(%s)) AS sim
            FROM customer_master
            WHERE 
                normalized_name ILIKE %s
                OR similarity(LOWER(customer_name), LOWER(%s)) > 0.4
            ORDER BY 
                (normalized_name = %s) DESC,
                (normalized_name ILIKE %s) DESC,
                similarity(LOWER(customer_name), LOWER(%s)) DESC
            LIMIT %s;
            """,
            [norm_input, like_pattern, norm_input, norm_input, like_pattern, norm_input, limit * 2]
        )

    if norm_rows:
        distinct_cids = {r["customer_id"] for r in norm_rows}
        if len(distinct_cids) == 1:
            # Unambiguous match!
            r = norm_rows[0]
            return ResolvedCustomer(
                customer_id=r["customer_id"],
                customer_name=r["customer_name"],
                normalized_name=r["normalized_name"],
                tally_id=r["tally_id"],
                route_number=r["route_number"],
                address=r["address"],
                phone=r["phone"],
                tier=2,
                status=CustomerResolutionStatus.RESOLVED,
                match_type="master_normalized_unambiguous",
            )
        else:
            # Multiple distinct Customer IDs matched
            # Try applying location / route hints
            filtered = norm_rows
            if route_hint is not None:
                filtered = [r for r in filtered if r.get("route_number") == route_hint]
            if location_hint:
                norm_loc = normalize_customer_name(location_hint)
                filtered = [r for r in filtered if r.get("address") and norm_loc in normalize_customer_name(r["address"])]

            distinct_filtered_cids = {r["customer_id"] for r in filtered}
            if len(distinct_filtered_cids) == 1:
                r = filtered[0]
                return ResolvedCustomer(
                    customer_id=r["customer_id"],
                    customer_name=r["customer_name"],
                    normalized_name=r["normalized_name"],
                    tally_id=r["tally_id"],
                    route_number=r["route_number"],
                    address=r["address"],
                    phone=r["phone"],
                    tier=2,
                    status=CustomerResolutionStatus.RESOLVED,
                    match_type="master_normalized_disambiguated",
                )

            # Still ambiguous: Explicitly return ambiguous status
            candidates = []
            seen_ids = set()
            for r in norm_rows:
                cid = r["customer_id"]
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    candidates.append({
                        "customer_id": cid,
                        "name": r["customer_name"],
                        "address": r.get("address") or "",
                        "route_number": r.get("route_number"),
                        "tally_id": r.get("tally_id"),
                    })

            return ResolvedCustomer(
                customer_id=None,
                customer_name=raw_input,
                normalized_name=norm_input,
                tally_id=None,
                route_number=None,
                address=None,
                phone=None,
                tier=2,
                status=CustomerResolutionStatus.AMBIGUOUS,
                candidates=candidates[:limit],
                match_type="master_normalized_ambiguous",
                message=f"Ambiguous: Normalized name matches multiple customer IDs ({len(candidates)} found)",
            )

    # ═══════════════════════════════════════════════════════════════════
    # TIER 3: Existing price-sheet customer ID as fallback (rate_cards)
    # ═══════════════════════════════════════════════════════════════════
    # 3A. Exact customer_id in rate_cards
    rc_id_rows = db.query(
        """
        SELECT DISTINCT
            rc.customer_id,
            rc.customer_name,
            rc.code AS tally_id,
            c.route_number,
            c.address,
            c.phone
        FROM rate_cards rc
        LEFT JOIN customers c ON rc.customer_id = c.customer_id
        WHERE rc.customer_id IS NOT NULL AND rc.customer_id ILIKE %s
        LIMIT 1;
        """,
        [raw_input]
    )
    if rc_id_rows:
        r = rc_id_rows[0]
        return ResolvedCustomer(
            customer_id=r["customer_id"],
            customer_name=r["customer_name"],
            normalized_name=normalize_customer_name(r["customer_name"]),
            tally_id=r.get("tally_id"),
            route_number=r.get("route_number"),
            address=r.get("address"),
            phone=r.get("phone"),
            tier=3,
            status=CustomerResolutionStatus.RESOLVED,
            match_type="rate_card_fallback_id",
        )

    # 3B. Customer name match in rate_cards
    rc_name_rows = db.query(
        """
        SELECT DISTINCT
            rc.customer_id,
            rc.customer_name,
            rc.code AS tally_id,
            c.route_number,
            c.address,
            c.phone,
            similarity(LOWER(rc.customer_name), LOWER(%s)) AS sim
        FROM rate_cards rc
        LEFT JOIN customers c ON rc.customer_id = c.customer_id
        WHERE 
            rc.customer_id IS NOT NULL
            AND (
                LOWER(rc.customer_name) = LOWER(%s)
                OR rc.customer_name ILIKE %s
                OR similarity(LOWER(rc.customer_name), LOWER(%s)) > 0.4
            )
        ORDER BY sim DESC
        LIMIT %s;
        """,
        [raw_input, raw_input, f"%{norm_input}%", raw_input, limit]
    )
    if rc_name_rows:
        distinct_rc_ids = {r["customer_id"] for r in rc_name_rows}
        if len(distinct_rc_ids) == 1:
            r = rc_name_rows[0]
            return ResolvedCustomer(
                customer_id=r["customer_id"],
                customer_name=r["customer_name"],
                normalized_name=normalize_customer_name(r["customer_name"]),
                tally_id=r.get("tally_id"),
                route_number=r.get("route_number"),
                address=r.get("address"),
                phone=r.get("phone"),
                tier=3,
                status=CustomerResolutionStatus.RESOLVED,
                match_type="rate_card_fallback_name",
            )
        else:
            candidates = [
                {
                    "customer_id": r["customer_id"],
                    "name": r["customer_name"],
                    "address": r.get("address") or "",
                    "route_number": r.get("route_number"),
                    "tally_id": r.get("tally_id"),
                }
                for r in rc_name_rows
            ]
            return ResolvedCustomer(
                customer_id=None,
                customer_name=raw_input,
                normalized_name=norm_input,
                tally_id=None,
                route_number=None,
                address=None,
                phone=None,
                tier=3,
                status=CustomerResolutionStatus.AMBIGUOUS,
                candidates=candidates,
                match_type="rate_card_fallback_ambiguous",
                message=f"Ambiguous: Rate cards match multiple customer IDs",
            )

    # ═══════════════════════════════════════════════════════════════════
    # TIER 4: Return "customer ID not found" without inventing a value
    # ═══════════════════════════════════════════════════════════════════
    return ResolvedCustomer(
        customer_id=None,
        customer_name=raw_input,
        normalized_name=norm_input,
        tally_id=None,
        route_number=None,
        address=None,
        phone=None,
        tier=4,
        status=CustomerResolutionStatus.NOT_FOUND,
        match_type="not_found",
        message="Customer ID not found",
    )


def resolve_tally_id(identifier: str) -> str | None:
    """
    Resolve Tally ID using authoritative priority:
    1. customer_master (by customer_id or exact customer_name)
    2. rate_cards (by customer_id or customer_name)
    3. Return None
    """
    if not identifier or not str(identifier).strip():
        return None

    raw_val = str(identifier).strip()

    # 1. Check customer_master
    master_rows = db.query(
        """
        SELECT tally_id 
        FROM customer_master 
        WHERE (customer_id ILIKE %s OR LOWER(customer_name) = LOWER(%s))
          AND tally_id IS NOT NULL 
          AND tally_id != ''
        LIMIT 1;
        """,
        [raw_val, raw_val]
    )
    if master_rows and master_rows[0].get("tally_id"):
        return master_rows[0]["tally_id"]

    # 2. Check rate_cards fallback
    rc_rows = db.query(
        """
        SELECT code AS tally_id
        FROM rate_cards
        WHERE (customer_id ILIKE %s OR customer_name ILIKE %s)
          AND code IS NOT NULL
          AND code != ''
        LIMIT 1;
        """,
        [raw_val, f"%{raw_val}%"]
    )
    if rc_rows and rc_rows[0].get("tally_id"):
        return rc_rows[0]["tally_id"]

    return None
