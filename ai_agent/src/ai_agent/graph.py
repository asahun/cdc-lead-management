import logging
import re
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from ai_agent.schemas import RunRequest
from ai_agent.settings import Settings
from ai_agent.tools.db import PostgresClient
from ai_agent.tools.ga_sos import lookup_business
from ai_agent.tools.gov_domain import extract_domain, is_federal_domain
from ai_agent.tools.places import lookup_place
from ai_agent.tools.web_search import build_dba_queries, build_out_of_state_queries, search_web
from ai_agent.utils.audit import add_error, end_step, ensure_audit, start_step
from ai_agent.utils.entity_rules import (
    CandidateScore,
    choose_candidate,
    classify_entity_type,
    government_validation_from_places,
    location_quality_with_source,
    score_candidates,
    strong_name_match,
)
from ai_agent.utils.llm import build_fallback_response, run_research

logger = logging.getLogger(__name__)

def _status_to_scenario(status: str | None) -> str:
    if not status:
        return "unknown"
    normalized = status.lower()
    if "active" in normalized:
        if "pending" in normalized:
            return "active_pending"
        if "noncompliance" in normalized or "non-compliance" in normalized:
            return "active_noncompliant"
        return "active"
    if "dissolved" in normalized:
        return "dissolved"
    if "withdrawn" in normalized or "revoked" in normalized or "terminated" in normalized:
        return "withdrawn_or_revoked"
    return "unknown"

def _has_strong_lead(results: list[dict[str, Any]], business_name: str, state: str) -> bool:
    if not results:
        return False
    name = business_name.lower()
    state_token = state.lower()
    for item in results:
        haystack = " ".join(
            [
                (item.get("title") or "").lower(),
                (item.get("snippet") or "").lower(),
            ]
        )
        if name in haystack and state_token in haystack:
            return True
    return False


def _has_official_county_contact(results: list[dict[str, Any]]) -> bool:
    for item in results:
        url = (item.get("url") or "").lower()
        title = (item.get("title") or "").lower()
        snippet = (item.get("snippet") or "").lower()
        if ".gov" in url and "county" in url and ("contact" in url or "contact" in title or "contact" in snippet):
            return True
    return False


def _county_pattern_match(owner_name: str) -> bool:
    return bool(re.search(r"\bcounty\b", (owner_name or "").lower()))


class AgentState(TypedDict, total=False):
    input: RunRequest
    normalized_name: str
    normalized_state: str
    entity_type: str
    entity_type_confidence: float
    entity_type_reason_code: str
    entity_type_needs_review: bool
    entity_type_validator: str | None
    entity_type_validator_evidence: dict[str, Any] | None
    context: dict[str, Any]
    ga_sos_result: dict[str, Any]
    ga_sos_candidates: list[CandidateScore]
    ga_sos_record: dict[str, Any] | None
    ga_sos_status: str | None
    ga_sos_name: str | None
    ga_sos_decision: str | None
    location_quality: str | None
    web_results: list[dict[str, Any]]
    web_search_plan: list[dict[str, Any]]
    web_strong_lead: bool
    resolution: dict[str, Any]
    places_profile: dict[str, Any] | None
    analysis: dict[str, Any]
    audit: dict[str, Any]
    response: dict[str, Any]


def normalize_input_node():
    def _node(state: AgentState) -> dict[str, Any]:
        audit = ensure_audit(state)
        step = start_step(audit, "normalize_input")
        request = state["input"]
        normalized_name = request.business_name.strip()
        normalized_state = request.state.strip().upper()[:2]
        end_step(step, "normalized")
        return {
            "normalized_name": normalized_name,
            "normalized_state": normalized_state,
            "audit": audit,
        }

    return _node


def classify_entity_type_node():
    def _node(state: AgentState) -> dict[str, Any]:
        audit = ensure_audit(state)
        step = start_step(audit, "classify_entity_type")
        request = state["input"]
        decision = classify_entity_type(
            request.business_name,
            request.holder_name_on_record,
            request.holder_known_address,
        )
        end_step(step, f"entity_type={decision.entity_type}")
        return {
            "entity_type": decision.entity_type,
            "entity_type_confidence": decision.confidence,
            "entity_type_reason_code": decision.reason_code,
            "entity_type_needs_review": decision.needs_review,
            "entity_type_validator": None,
            "entity_type_validator_evidence": None,
            "audit": audit,
        }

    return _node


def load_context_from_db_node(db: PostgresClient):
    def _node(state: AgentState) -> dict[str, Any]:
        audit = ensure_audit(state)
        step = start_step(audit, "load_context_from_db")
        try:
            context = db.load_context(
                state.get("normalized_name") or state["input"].business_name,
                state.get("normalized_state") or state["input"].state,
            )
            end_step(step, "context loaded")
            return {"context": context, "audit": audit}
        except Exception as exc:
            add_error(audit, f"load_context_from_db error: {exc}")
            end_step(step, "context failed")
            return {"context": {}, "audit": audit}

    return _node


def lookup_ga_sos_node(settings: Settings, db: PostgresClient):
    def _node(state: AgentState) -> dict[str, Any]:
        audit = ensure_audit(state)
        step = start_step(audit, "lookup_ga_sos")
        try:
            entity_type = state.get("entity_type")
            if entity_type in {"government_federal", "government_state_local", "estate_trust"}:
                holder_address = state["input"].holder_known_address or {}
                end_step(step, f"skipped (entity_type={entity_type})")
                return {
                    "ga_sos_result": {"records": []},
                    "ga_sos_record": None,
                    "ga_sos_decision": "skipped",
                    "location_quality": location_quality_with_source(
                        holder_address,
                        state["input"].address_source or "property_mailing",
                    ),
                    "audit": audit,
                }

            name = state.get("normalized_name") or state["input"].business_name
            logger.info("GA SOS lookup start: name=%s", name)
            result = lookup_business(name, state.get("normalized_state") or state["input"].state, settings)

            records = result.get("records", []) if isinstance(result, dict) else []
            holder_address = state["input"].holder_known_address or {}
            location_quality = location_quality_with_source(
                holder_address,
                state["input"].address_source or "property_mailing",
            )
            scored = score_candidates(
                state["input"].business_name,
                holder_address,
                records,
                state["input"].last_activity_date,
            )
            selected, decision = choose_candidate(scored)
            if len(records) == 1 and strong_name_match(state["input"].business_name, records[0].get("business_name") or ""):
                selected = records[0]
                decision = "selected_single"
            ga_status = selected.get("entity_status") if selected else None
            ga_name = selected.get("business_name") if selected else None
            logger.info(
                "GA SOS lookup done: records=%d decision=%s",
                len(records),
                decision,
            )

            end_step(step, f"records={len(records)}, decision={decision}")
            return {
                "ga_sos_result": result,
                "ga_sos_candidates": scored,
                "ga_sos_record": selected,
                "ga_sos_status": ga_status,
                "ga_sos_name": ga_name,
                "ga_sos_decision": decision,
                "location_quality": location_quality,
                "audit": audit,
            }
        except Exception as exc:
            add_error(audit, f"lookup_ga_sos error: {exc}")
            end_step(step, "lookup failed")
            return {"ga_sos_result": {"records": []}, "audit": audit}

    return _node


def web_search_evidence_node(settings: Settings, db: PostgresClient):
    def _node(state: AgentState) -> dict[str, Any]:
        audit = ensure_audit(state)
        step = start_step(audit, "web_search_evidence")
        try:
            name = state.get("ga_sos_name") or state.get("normalized_name") or state["input"].business_name
            region = state.get("normalized_state") or state["input"].state
            status = state.get("ga_sos_status")
            entity_type = state.get("entity_type")
            sos_records = (state.get("ga_sos_result") or {}).get("records", [])
            web_plan: list[dict[str, Any]] = []
            strong_lead = False

            if entity_type == "business" and not sos_records:
                pass1_queries = build_dba_queries(name, region)
                results = search_web(name, region, settings, queries=pass1_queries)
                strong_lead = _has_strong_lead(results, name, region)
                web_plan.append({"pass": "dba_variant", "queries": pass1_queries, "results": len(results)})

                if not strong_lead:
                    pass2_queries = build_out_of_state_queries(name)
                    more_results = search_web(name, region, settings, queries=pass2_queries)
                    results = results + more_results
                    web_plan.append(
                        {
                            "pass": "out_of_state",
                            "queries": pass2_queries,
                            "results": len(more_results),
                        }
                    )
                query_notes = f"dba_queries={len(pass1_queries)}"
                if len(web_plan) > 1:
                    query_notes += f", out_of_state_queries={len(pass2_queries)}"
                end_step(
                    step,
                    f"{query_notes}, pass1_results={web_plan[0]['results']}, pass2_results={web_plan[1]['results'] if len(web_plan) > 1 else 0}",
                )
                return {
                    "web_results": results,
                    "web_search_plan": web_plan,
                    "web_strong_lead": strong_lead,
                    "audit": audit,
                }

            results = search_web(name, region, settings, status)
            web_plan.append({"pass": "default", "queries": [], "results": len(results)})
            end_step(step, f"results={len(results)}, branch=default")
            return {
                "web_results": results,
                "web_search_plan": web_plan,
                "web_strong_lead": strong_lead,
                "audit": audit,
            }
        except Exception as exc:
            add_error(audit, f"web_search_evidence error: {exc}")
            end_step(step, "search failed")
            return {"web_results": [], "audit": audit}

    return _node


def lookup_places_node(settings: Settings):
    def _node(state: AgentState) -> dict[str, Any]:
        audit = ensure_audit(state)
        step = start_step(audit, "lookup_places")
        try:
            name = state.get("ga_sos_name") or state.get("normalized_name") or state["input"].business_name
            profile = lookup_place(
                name,
                settings,
                city=state["input"].city,
                state=state.get("normalized_state") or state["input"].state,
            )
            end_step(step, "places fetched" if profile else "places empty")
            return {"places_profile": profile, "audit": audit}
        except Exception as exc:
            add_error(audit, f"lookup_places error: {exc}")
            end_step(step, "places failed")
            return {"places_profile": None, "audit": audit}

    return _node


def resolve_entity_and_scenario_node(settings: Settings):
    def _node(state: AgentState) -> dict[str, Any]:
        audit = ensure_audit(state)
        step = start_step(audit, "resolve_entity_and_scenario")
        try:
            request = state["input"]
            entity_type = state.get("entity_type") or "business"
            entity_type_confidence = float(state.get("entity_type_confidence") or 0.0)
            entity_type_reason = state.get("entity_type_reason_code") or "BUSINESS_DEFAULT"
            entity_type_needs_review = bool(state.get("entity_type_needs_review"))
            entity_type_validator = state.get("entity_type_validator")
            entity_type_validator_evidence = state.get("entity_type_validator_evidence")
            location_quality = state.get("location_quality") or "LOW"
            scored = state.get("ga_sos_candidates") or []
            ga_sos_decision = state.get("ga_sos_decision") or "no_candidates"
            web_strong_lead = bool(state.get("web_strong_lead"))
            web_plan = state.get("web_search_plan") or []
            sos_records = (state.get("ga_sos_result") or {}).get("records", [])
            selected_candidate = state.get("ga_sos_record")
            top_score = scored[0].score if scored else 0.0
            confidence = float(top_score) if scored else 0.0
            needs_review = True
            reason_code = None
            scenario = "unknown"
            web_has_official_county_contact = _has_official_county_contact(state.get("web_results") or [])
            county_pattern_match = _county_pattern_match(request.business_name)

            if entity_type in {"ambiguous", "government_state_local", "government_federal"} and (
                entity_type_needs_review or entity_type == "ambiguous"
            ):
                validation = government_validation_from_places(request.business_name, state.get("places_profile"))
                if validation:
                    entity_type = validation.entity_type
                    entity_type_confidence = validation.confidence
                    entity_type_reason = validation.reason_code
                    entity_type_needs_review = validation.needs_review
                    entity_type_validator = "places"
                    entity_type_validator_evidence = {
                        "website_uri": (state.get("places_profile") or {}).get("website_uri"),
                        "primary_type": (state.get("places_profile") or {}).get("primary_type"),
                        "types": (state.get("places_profile") or {}).get("types"),
                        "display_name": (state.get("places_profile") or {}).get("display_name"),
                        "name_similarity": (state.get("places_profile") or {}).get("name_similarity"),
                    }
                    website_uri = (state.get("places_profile") or {}).get("website_uri")
                    domain = extract_domain(website_uri or "")
                    if domain and (domain.endswith(".gov") or domain.endswith(".mil")):
                        federal = is_federal_domain(domain, settings)
                        if federal:
                            entity_type = "government_federal"
                            entity_type_confidence = 0.9
                            entity_type_reason = "GOV_VALIDATED_BY_GOV_DOMAIN"
                            entity_type_needs_review = False
                            entity_type_validator = "gsa_site_scanning"
                            entity_type_validator_evidence = {
                                "domain": domain,
                                "validated": True,
                            }
                elif entity_type == "ambiguous" and settings.google_cse_api_key and settings.google_cse_cx:
                    gov_query = f"site:.gov \"{request.business_name}\""
                    if request.city or request.state:
                        gov_query = f"{gov_query} {request.city or ''} {request.state or ''}".strip()
                    gov_results = search_web(
                        request.business_name,
                        request.state,
                        settings,
                        queries=[gov_query],
                    )
                    if gov_results:
                        entity_type = "government_state_local"
                        entity_type_confidence = 0.6
                        entity_type_reason = "GOV_VALIDATED_BY_GOV_DOMAIN"
                        entity_type_needs_review = True
                        entity_type_validator = "gov_domain_search"
                        top_url = gov_results[0].get("url")
                        domain = extract_domain(top_url or "")
                        entity_type_validator_evidence = {
                            "query": gov_query,
                            "top_url": top_url,
                            "domain": domain,
                        }
                        if domain and (domain.endswith(".gov") or domain.endswith(".mil")):
                            federal = is_federal_domain(domain, settings)
                            if federal:
                                entity_type = "government_federal"
                                entity_type_confidence = 0.85
                                entity_type_reason = "GOV_VALIDATED_BY_GOV_DOMAIN"
                                entity_type_needs_review = False
                                entity_type_validator = "gsa_site_scanning"
                                entity_type_validator_evidence = {
                                    "domain": domain,
                                    "validated": True,
                                }

            if entity_type == "estate_trust":
                needs_review = True
                confidence = 0.0
                selected_candidate = None
                reason_code = "NOT_A_BUSINESS_ENTITY"
            elif entity_type == "ambiguous":
                needs_review = True
                confidence = entity_type_confidence
                selected_candidate = None
                reason_code = entity_type_reason
            elif entity_type in {"government_federal", "government_state_local"}:
                needs_review = entity_type_needs_review
                confidence = entity_type_confidence
                selected_candidate = {
                    "business_name": request.business_name,
                    "entity_status": None,
                }
                reason_code = entity_type_reason
            elif not sos_records:
                needs_review = True
                confidence = 0.0
                selected_candidate = None
                if web_strong_lead:
                    reason_code = "POSSIBLE_OUT_OF_STATE_OR_UNREGISTERED"
                elif state.get("web_results"):
                    reason_code = "LIKELY_DBA_OR_NAME_VARIANT"
                else:
                    reason_code = "SEARCH_LIMITATION_PROVIDER_GAP"
            else:
                if len(sos_records) == 1:
                    candidate = sos_records[0]
                    if (
                        entity_type == "business"
                        and strong_name_match(request.business_name, candidate.get("business_name") or "")
                    ):
                        selected_candidate = candidate
                        needs_review = False
                        reason_code = "RESOLVED_SINGLE_SOS_MATCH"
                    else:
                        selected_candidate = None
                        needs_review = True
                        reason_code = "NAME_MISMATCH"
                elif ga_sos_decision in {"selected_confident", "selected_single"} and confidence >= 0.85:
                    needs_review = False
                    reason_code = "RESOLVED_CONFIDENT_MATCH"
                elif ga_sos_decision == "selected_tentative" and confidence >= 0.65:
                    needs_review = True
                    reason_code = "WEB_EVIDENCE_STRONG" if web_has_official_county_contact else "WEB_EVIDENCE_WEAK"
                else:
                    needs_review = True
                    selected_candidate = None
                    reason_code = "WEB_EVIDENCE_STRONG" if web_has_official_county_contact else "WEB_EVIDENCE_WEAK"

            if selected_candidate:
                scenario = _status_to_scenario(selected_candidate.get("entity_status"))

            candidates_payload = []
            for item in scored[:5]:
                candidates_payload.append(
                    {
                        "record": item.record,
                        "score": item.score,
                        "components": item.components,
                        "reasons": item.reasons,
                        "location_quality": item.location_quality,
                    }
                )
            resolution = {
                "entity_type": entity_type,
                "entity_type_confidence": round(entity_type_confidence, 3),
                "entity_type_reason_code": entity_type_reason,
                "entity_type_needs_review": entity_type_needs_review,
                "entity_type_validator": entity_type_validator,
                "entity_type_validator_evidence": entity_type_validator_evidence,
                "selected_candidate": selected_candidate if not needs_review else None,
                "confidence": round(confidence, 3),
                "needs_review": needs_review,
                "reason_code": reason_code,
                "decision": ga_sos_decision,
                "location_evidence_quality": location_quality,
                "candidates": candidates_payload,
                "web_search_plan": web_plan,
                "scenario": scenario,
                "guardrails": {
                    "county_pattern_match": county_pattern_match,
                    "places_name_similarity": (state.get("places_profile") or {}).get("name_similarity"),
                    "places_selected_place_id": (state.get("places_profile") or {}).get("place_id"),
                    "web_official_domain_detected": web_has_official_county_contact,
                },
            }

            web_pages = []
            for idx, item in enumerate(state.get("web_results", []), start=1):
                web_pages.append(
                    {
                        "id": f"web_{idx}",
                        "url": item.get("url") or "",
                        "title": item.get("title") or "",
                        "type": "web",
                        "content": item.get("snippet") or "",
                    }
                )

            ga_record = state.get("ga_sos_record")
            if isinstance(ga_record, dict):
                ga_record = dict(ga_record)
                ga_record.pop("registered_agent", None)

            sos_result = state.get("ga_sos_result") or {}
            analysis = run_research(
                settings,
                request.business_name,
                request.state,
                request.holder_name_on_record,
                request.last_activity_date,
                request.property_report_year,
                request.city,
                request.ownerrelation,
                request.propertytypedescription,
                request.holder_known_address,
                ga_record,
                sos_result.get("search_names_tried", []),
                sos_result.get("matched_name"),
                web_pages,
                state.get("places_profile"),
            )
            if not analysis:
                analysis = build_fallback_response(
                    request.business_name,
                    request.state,
                    ga_record,
                    sos_result.get("search_names_tried", []),
                    state.get("places_profile"),
                )
            if isinstance(analysis, dict):
                query_context = analysis.get("query_context")
                if not isinstance(query_context, dict):
                    query_context = {}
                    analysis["query_context"] = query_context
                query_context.setdefault("owner_name_input", request.business_name)
                query_context.setdefault("state_focus", request.state)
                query_context.setdefault("phase1_ga_sos_found", bool(ga_record))
                query_context.setdefault(
                    "phase1_variants_checked",
                    sos_result.get("search_names_tried", []),
                )
                query_context.setdefault(
                    "phase1_note",
                    "GA SOS results provided as context only.",
                )

                context_inputs = analysis.get("context_inputs")
                if not isinstance(context_inputs, dict):
                    context_inputs = {}
                    analysis["context_inputs"] = context_inputs
                if ga_record:
                    context_inputs["ga_sos_selected_record"] = ga_record
                else:
                    context_inputs.setdefault("ga_sos_selected_record", None)
                if state.get("places_profile"):
                    context_inputs["google_places_context"] = state.get("places_profile")
                else:
                    context_inputs.setdefault("google_places_context", None)
                if entity_type in {"government_federal", "government_state_local"} and not needs_review:
                    selected = analysis.get("selected_entitled_entity")
                    if not isinstance(selected, dict):
                        selected = {}
                        analysis["selected_entitled_entity"] = selected
                    selected["selected_rank"] = 1
                    selected["entitled_business_name"] = request.business_name
                    selected["operating_status_web"] = "operating"
                    selected["website"] = (state.get("places_profile") or {}).get("website_uri")
                    selected["mailing_address_web"] = (state.get("places_profile") or {}).get("formatted_address")
                    selected["best_outreach_channel"] = "contact_form" if selected.get("website") else "unknown"
                    selected["outreach_contacts"] = {
                        "phones": [
                            (state.get("places_profile") or {}).get("national_phone"),
                        ]
                        if (state.get("places_profile") or {}).get("national_phone")
                        else [],
                        "emails": [],
                        "contact_forms": [],
                        "named_contacts": [],
                    }
                    selected["why_selected"] = f"Government entity classified by rules. Reason: {entity_type_reason}."
                    selected["source_urls"] = [
                        (state.get("places_profile") or {}).get("website_uri"),
                    ]
                    selected["note_on_context_only_sources"] = (
                        "Government classification bypasses GA SOS. Places/Gov domain used for validation."
                    )
                if needs_review and not selected_candidate:
                    selected = analysis.get("selected_entitled_entity")
                    if not isinstance(selected, dict):
                        selected = {}
                        analysis["selected_entitled_entity"] = selected
                    selected["selected_rank"] = 1
                    selected["entitled_business_name"] = "Unknown"
                    selected["operating_status_web"] = "unknown"
                    selected["website"] = None
                    selected["mailing_address_web"] = None
                    selected["best_outreach_channel"] = "unknown"
                    selected["outreach_contacts"] = {
                        "phones": [],
                        "emails": [],
                        "contact_forms": [],
                        "named_contacts": [],
                    }
                    selected["why_selected"] = (
                        f"Insufficient evidence to select a single entity. Reason: {reason_code or 'NEEDS_REVIEW'}."
                    )
                    selected["source_urls"] = []
                    selected["note_on_context_only_sources"] = (
                        "GA SOS and Google Places are context only until resolution confidence is high."
                    )
            end_step(step, f"analysis ready | needs_review={needs_review} reason={reason_code}")
            return {"analysis": analysis, "resolution": resolution, "audit": audit}
        except Exception as exc:
            add_error(audit, f"resolve_entity_and_scenario error: {exc}")
            end_step(step, "analysis failed")
            return {"analysis": {}, "audit": audit}

    return _node


def build_response_with_audit_node():
    def _node(state: AgentState) -> dict[str, Any]:
        audit = ensure_audit(state)
        step = start_step(audit, "build_response_with_audit")
        response = {
            "input": state["input"].model_dump(),
            "analysis": state.get("analysis", {}),
            "resolution": state.get("resolution", {}),
            "audit": audit,
        }
        end_step(step, "response ready")
        return {"response": response, "audit": audit}

    return _node


def build_graph(db: PostgresClient, settings: Settings):
    graph = StateGraph(AgentState)
    graph.add_node("normalize_input", normalize_input_node())
    graph.add_node("classify_entity_type", classify_entity_type_node())
    graph.add_node("load_context_from_db", load_context_from_db_node(db))
    graph.add_node("lookup_ga_sos", lookup_ga_sos_node(settings, db))
    graph.add_node("web_search_evidence", web_search_evidence_node(settings, db))
    graph.add_node("lookup_places", lookup_places_node(settings))
    graph.add_node("resolve_entity_and_scenario", resolve_entity_and_scenario_node(settings))
    graph.add_node("build_response_with_audit", build_response_with_audit_node())

    graph.set_entry_point("normalize_input")
    graph.add_edge("normalize_input", "classify_entity_type")
    graph.add_edge("classify_entity_type", "load_context_from_db")
    graph.add_edge("load_context_from_db", "lookup_ga_sos")
    graph.add_edge("lookup_ga_sos", "web_search_evidence")
    graph.add_edge("web_search_evidence", "lookup_places")
    graph.add_edge("lookup_places", "resolve_entity_and_scenario")
    graph.add_edge("resolve_entity_and_scenario", "build_response_with_audit")
    graph.add_edge("build_response_with_audit", END)

    return graph.compile()
