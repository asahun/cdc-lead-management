"""Google Custom Search Engine (CSE) query selector based on SOS status."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CSEQueryPack:
    """Return type: a dict of named CSE queries (strings)."""
    scenario: str
    queries: Dict[str, str]


class CSEQuerySelector:
    """
    Selects a Google CSE query JSON (dict of query strings) based on:
      - GA SOS status (string) OR
      - a SOS result object (dict-like) containing a status field OR
      - None (no GA SOS record)

    Intent:
      - If GA SOS is missing -> focus on: (a) DBA/trade-name discovery, (b) other-state registration, (c) official site/contact.
      - If GA SOS is active-like -> focus on: official identity + corporate contact + potential parent/affiliate signals.
      - If GA SOS is inactive/dissolved/etc -> focus on: successor/rename/acquisition + where operations moved + who to contact now.
      - If merged/consolidated -> heavy successor queries.
      - If pending/hold/investigation/flawed -> confirm identity + filings + current contact, avoid "successor" unless evidence appears.
    """

    # ---- Public API ----

    def get_cse_queries(
        self,
        sos: Optional[Union[str, Dict[str, Any]]] = None,
        *,
        business_name: str,
        state_full: str = "Georgia",
        city: Optional[str] = None,
    ) -> CSEQueryPack:
        """
        Get CSE queries based on SOS status.
        
        Args:
            sos: SOS status string, SOS record dict, or None
            business_name: Business name to search for
            state_full: Full state name (default: "Georgia")
            city: Optional city name for local footprint queries
            
        Returns:
            CSEQueryPack with scenario name and dictionary of queries
        """
        status = self._extract_status(sos)
        scenario = self._scenario_from_status(status)
        
        logger.debug(f"CSEQuerySelector: status='{status}', scenario='{scenario}' for business='{business_name}'")
        
        # Build query pack for scenario
        if scenario == "no_ga_sos_record":
            queries = self._build_no_sos_queries(business_name, state_full, city)
        elif scenario == "active_like":
            queries = self._build_active_queries(business_name, state_full, city)
        elif scenario == "merged_like":
            queries = self._build_merged_queries(business_name, state_full, city)
        elif scenario == "inactive_like":
            queries = self._build_inactive_queries(business_name, state_full, city)
        elif scenario == "pending_or_filing_like":
            queries = self._build_pending_queries(business_name, state_full, city)
        elif scenario == "risk_or_review_like":
            queries = self._build_risk_queries(business_name, state_full, city)
        else:
            # Fallback
            logger.warning(f"CSEQuerySelector: Unknown scenario '{scenario}', falling back to active_like")
            queries = self._build_active_queries(business_name, state_full, city)
        
        # Validate queries are non-empty
        validated_queries = {k: v for k, v in queries.items() if v and v.strip()}
        
        return CSEQueryPack(scenario=scenario, queries=validated_queries)

    # ---- Status extraction & scenario mapping ----

    def _extract_status(self, sos: Optional[Union[str, Dict[str, Any]]]) -> Optional[str]:
        """
        Accepts None, a status string, or a SOS dict. Returns normalized status string or None.
        
        Args:
            sos: SOS status string, SOS record dict, or None
            
        Returns:
            Normalized status string or None
        """
        if sos is None:
            return None

        if isinstance(sos, str):
            return self._norm_status(sos)

        # Dict-like SOS record
        if isinstance(sos, dict):
            try:
                # Try common status field names
                for key in ("entity_status", "status", "status_desc", "status_description", "business_status"):
                    val = sos.get(key)
                    if isinstance(val, str) and val.strip():
                        return self._norm_status(val)
                # Sometimes nested
                meta = sos.get("meta") or sos.get("sos") or {}
                if isinstance(meta, dict):
                    for key in ("entity_status", "status", "status_desc"):
                        val = meta.get(key)
                        if isinstance(val, str) and val.strip():
                            return self._norm_status(val)
            except Exception as e:
                logger.warning(f"CSEQuerySelector: Error extracting status from SOS dict: {e}")
                return None

        return None

    def _norm_status(self, s: str) -> str:
        """
        Normalize status string: uppercase, remove periods, normalize whitespace.
        
        Examples:
            "Admin. Dissolved" -> "ADMIN DISSOLVED"
            "Active/Compliance" -> "ACTIVE/COMPLIANCE"
        """
        # Remove periods, then normalize
        s = s.replace(".", "")
        # Uppercase and normalize whitespace
        s = " ".join(s.strip().upper().split())
        return s

    def _scenario_from_status(self, status: Optional[str]) -> str:
        """
        Map normalized status to scenario name.
        
        Args:
            status: Normalized status string or None
            
        Returns:
            Scenario name string
        """
        if status is None:
            return "no_ga_sos_record"

        # Normalize once
        st = status

        # Merged / consolidated
        merged_like = {
            "MERGED",
            "WITHDRAWN/MERGED",
            "WITHDRAWN / MERGED",
            "CONSOLIDATED",
        }
        if st in merged_like:
            return "merged_like"

        # Active-ish
        active_like = {
            "ACTIVE",
            "ACTIVE/COMPLIANCE",
            "ACTIVE / COMPLIANCE",
            "ACTIVE/NONCOMPLIANCE",
            "ACTIVE / NONCOMPLIANCE",
            "ACTIVE PENDING",
        }
        if st in active_like:
            return "active_like"

        # Pending / filed / deficient
        pending_like = {
            "FILED",
            "FLAWED/DEFICIENT",
            "FLAWED / DEFICIENT",
            "NON-QUALIFYING/NON-FILING",
            "NON-QUALIFYING / NON-FILING",
            "ELECTION TO LLC/LP",
            "ELECTION TO LLC / LP",
        }
        if st in pending_like:
            return "pending_or_filing_like"

        # Risk / review / hold / investigation
        risk_like = {
            "HOLD",
            "UNDER INVESTIGATION",
            "SEE NOTEPAD",
        }
        if st in risk_like:
            return "risk_or_review_like"

        # Inactive-ish bucket (includes admin dissolved, revoked, withdrawn, etc.)
        inactive_like = {
            "ADMIN DISSOLVED",
            "ADMIN DISSOLVED/NONPAYMENT",
            "ADMIN DISSOLVED / NONPAYMENT",
            "ADMIN DISSOLVED/REVOKED",
            "ADMIN DISSOLVED / REVOKED",
            "CANCELLED",
            "CONVERTED",
            "DISSOLVED",
            "EXPIRED",
            "INACTIVE",
            "JUDICIAL DISSOLUTION",
            "NONCOMPLIANCE/NONPAYMENT",
            "NONCOMPLIANCE / NONPAYMENT",
            "REDEEMED",
            "REVOKED",
            "TERMINATED",
            "VOID",
            "WITHDRAWN",
        }
        if st in inactive_like:
            return "inactive_like"

        # Default to active_like for unknown statuses
        logger.debug(f"CSEQuerySelector: Unknown status '{st}', defaulting to active_like scenario")
        return "active_like"

    # ---- Query templates (your style, expanded per scenario) ----

    def _base_negative_filters(self) -> str:
        """Base negative filters to exclude job sites and similar noise."""
        return "-jobs -hiring -careers -glassdoor -indeed -ziprecruiter"

    def _q_official_identity_with_state(self, business_name: str, state_full: str) -> str:
        """Query for official identity with state."""
        neg = self._base_negative_filters()
        return f'"{business_name}" "{state_full}" (Inc OR LLC OR Corporation OR "Company" OR "Official Site") {neg}'

    def _q_official_identity_no_state(self, business_name: str) -> str:
        """Query for official identity without state."""
        neg = self._base_negative_filters()
        return f'"{business_name}" (Inc OR LLC OR Corporation OR "Company" OR "Official Site") {neg}'

    def _q_hq_contact(self, business_name: str) -> str:
        """Query for HQ / corporate contact information."""
        neg = self._base_negative_filters()
        return (
            f'"{business_name}" ("headquarters" OR "corporate office" OR "corporate headquarters" '
            f'OR "contact" OR "phone" OR address OR "investor relations") {neg}'
        )

    def _q_successor_rename_acquisition(self, business_name: str) -> str:
        """Query for successor / rename / acquisition information."""
        neg = self._base_negative_filters()
        return (
            f'"{business_name}" (acquisition OR acquired OR merger OR merged OR "now part of" OR subsidiary '
            f'OR "formerly known as" OR "f/k/a" OR "now known as" OR "name change" OR rebranded '
            f'OR "sold to" OR "division of") {neg}'
        )

    def _q_ga_local_footprint(self, business_name: str, city: Optional[str]) -> Optional[str]:
        """Query for GA local footprint (requires city)."""
        if not city:
            return None
        neg = self._base_negative_filters()
        return f'"{business_name}" "{city}" GA ("hours" OR "directions" OR "phone" OR address OR "contact") {neg}'

    def _q_dba_trade_name(self, business_name: str, state_full: str) -> str:
        """Query for DBA / trade name discovery (useful when no GA SOS record)."""
        neg = self._base_negative_filters()
        return (
            f'"{business_name}" (DBA OR "d/b/a" OR "doing business as" OR "trade name" OR "assumed name") '
            f'"{state_full}" {neg}'
        )

    def _q_other_state_registration(self, business_name: str) -> str:
        """Query for other state registration (when no GA SOS record)."""
        neg = self._base_negative_filters()
        return f'"{business_name}" ("Secretary of State" OR "business search" OR "entity search" OR "registered in") {neg}'

    def _q_parent_affiliate_signals(self, business_name: str) -> str:
        """Query for parent / affiliate / holding company relationships."""
        neg = self._base_negative_filters()
        return (
            f'"{business_name}" (parent OR "holding company" OR "owned by" OR subsidiary OR affiliate OR "a subsidiary of") {neg}'
        )

    # ---- Scenario builders ----

    def _build_no_sos_queries(self, business_name: str, state_full: str, city: Optional[str]) -> Dict[str, str]:
        """Build queries when no GA SOS record found."""
        queries: Dict[str, str] = {
            "official_identity_no_state": self._q_official_identity_no_state(business_name),
            "hq_contact": self._q_hq_contact(business_name),
            "dba_trade_name": self._q_dba_trade_name(business_name, state_full),
            "other_state_registration": self._q_other_state_registration(business_name),
        }
        q_local = self._q_ga_local_footprint(business_name, city)
        if q_local:
            queries["ga_local_footprint"] = q_local
        return queries

    def _build_active_queries(self, business_name: str, state_full: str, city: Optional[str]) -> Dict[str, str]:
        """Build queries for active-like entities."""
        queries: Dict[str, str] = {
            "official_identity_with_state": self._q_official_identity_with_state(business_name, state_full),
            "hq_contact": self._q_hq_contact(business_name),
            "parent_affiliate_signals": self._q_parent_affiliate_signals(business_name),
        }
        q_local = self._q_ga_local_footprint(business_name, city)
        if q_local:
            queries["ga_local_footprint"] = q_local
        return queries

    def _build_inactive_queries(self, business_name: str, state_full: str, city: Optional[str]) -> Dict[str, str]:
        """Build queries for inactive/dissolved entities (focus on successor + current operations)."""
        queries: Dict[str, str] = {
            "successor_rename_acquisition": self._q_successor_rename_acquisition(business_name),
            "official_identity_no_state": self._q_official_identity_no_state(business_name),
            "hq_contact": self._q_hq_contact(business_name),
            "other_state_registration": self._q_other_state_registration(business_name),
        }
        q_local = self._q_ga_local_footprint(business_name, city)
        if q_local:
            queries["ga_local_footprint"] = q_local
        return queries

    def _build_merged_queries(self, business_name: str, state_full: str, city: Optional[str]) -> Dict[str, str]:
        """Build queries for merged/consolidated entities (heavy successor focus)."""
        queries: Dict[str, str] = {
            "successor_rename_acquisition": self._q_successor_rename_acquisition(business_name),
            "hq_contact": self._q_hq_contact(business_name),
            "official_identity_no_state": self._q_official_identity_no_state(business_name),
        }
        q_local = self._q_ga_local_footprint(business_name, city)
        if q_local:
            queries["ga_local_footprint"] = q_local
        return queries

    def _build_pending_queries(self, business_name: str, state_full: str, city: Optional[str]) -> Dict[str, str]:
        """Build queries for filed/deficient/non-qualifying entities (confirm identity + contact, not successor-first)."""
        queries: Dict[str, str] = {
            "official_identity_with_state": self._q_official_identity_with_state(business_name, state_full),
            "hq_contact": self._q_hq_contact(business_name),
            "other_state_registration": self._q_other_state_registration(business_name),
        }
        q_local = self._q_ga_local_footprint(business_name, city)
        if q_local:
            queries["ga_local_footprint"] = q_local
        return queries

    def _build_risk_queries(self, business_name: str, state_full: str, city: Optional[str]) -> Dict[str, str]:
        """Build queries for hold/investigation/notepad entities (conservative: confirm official channels + contact)."""
        queries: Dict[str, str] = {
            "official_identity_with_state": self._q_official_identity_with_state(business_name, state_full),
            "hq_contact": self._q_hq_contact(business_name),
            "official_identity_no_state": self._q_official_identity_no_state(business_name),
        }
        q_local = self._q_ga_local_footprint(business_name, city)
        if q_local:
            queries["ga_local_footprint"] = q_local
        return queries

