from typing import Any

import requests
from bs4 import BeautifulSoup

from ai_agent.settings import Settings


def _scrape_text(url: str, settings: Settings) -> str | None:
    try:
        resp = requests.get(url, timeout=settings.web_scrape_timeout)
        resp.raise_for_status()
    except Exception:
        return None

    content_type = (resp.headers.get("content-type") or "").lower()
    if "application/pdf" in content_type or url.lower().endswith(".pdf"):
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text().splitlines() if line.strip())
    if len(text) > settings.web_scrape_max_chars:
        text = text[: settings.web_scrape_max_chars]
    return text


def _build_queries(business_name: str, state: str, ga_status: str | None) -> list[str]:
    base = business_name.strip()
    state = state.strip()
    status = (ga_status or "").lower()
    queries = [
        f"\"{base}\" {state} secretary of state",
        f"\"{base}\" official website",
        f"\"{base}\" {state} business entity search",
        f"\"{base}\" registered agent",
        f"\"{base}\" unclaimed property",
        f"\"{base}\" headquarters address",
    ]

    if "dissolved" in status or "withdrawn" in status:
        queries.extend(
            [
                f"\"{base}\" dissolved",
                f"\"{base}\" successor",
                f"\"{base}\" acquired by",
                f"\"{base}\" merger",
            ]
        )
    else:
        queries.extend(
            [
                f"\"{base}\" parent company",
                f"\"{base}\" subsidiary",
                f"\"{base}\" treasury contact",
            ]
        )

    queries.extend(
        [
            f"site:ga.gov \"{base}\"",
            f"site:.gov \"{base}\"",
        ]
    )

    return queries


def _build_dba_queries(business_name: str, state: str) -> list[str]:
    base = business_name.strip()
    state = state.strip()
    return [
        f"\"{base}\" dba",
        f"\"{base}\" \"doing business as\"",
        f"\"{base}\" assumed name {state}",
        f"\"{base}\" trade name {state}",
        f"\"{base}\" owner entity",
        f"\"{base}\" company profile",
    ]


def _build_out_of_state_queries(business_name: str) -> list[str]:
    base = business_name.strip()
    return [
        f"\"{base}\" foreign entity",
        f"\"{base}\" secretary of state",
        f"\"{base}\" corporation lookup",
        f"\"{base}\" business registry",
        f"\"{base}\" site:.gov",
    ]


def search_web(
    business_name: str,
    state: str,
    settings: Settings,
    ga_status: str | None = None,
    queries: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Google CSE web search; returns top snippets and optional scraped text."""
    if not settings.google_cse_api_key or not settings.google_cse_cx:
        return []

    queries = queries or _build_queries(business_name, state, ga_status)
    queries = queries[: settings.web_search_max_queries]

    items_by_url: dict[str, dict[str, Any]] = {}

    for q in queries:
        params = {
            "key": settings.google_cse_api_key,
            "cx": settings.google_cse_cx,
            "q": q,
            "num": 5,
        }
        try:
            resp = requests.get(
                "https://customsearch.googleapis.com/customsearch/v1",
                params=params,
                timeout=settings.google_cse_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            continue

        for item in data.get("items", []) or []:
            url = item.get("link") or ""
            if not url or url in items_by_url:
                continue
            items_by_url[url] = {
                "source": "web",
                "title": item.get("title") or "",
                "url": url,
                "snippet": item.get("snippet") or "",
                "confidence": 0.3,
            }

    items = list(items_by_url.values())

    if not settings.web_scrape_enabled:
        return items

    scraped = []
    for item in items[: settings.web_scrape_max_pages]:
        url = item.get("url")
        if not url:
            continue
        text = _scrape_text(url, settings)
        if not text:
            continue
        snippet = text[:280]
        scraped.append(
            {
                "source": "web",
                "title": item.get("title") or "",
                "url": url,
                "snippet": snippet,
                "confidence": 0.5,
            }
        )

    return items + scraped


def build_dba_queries(business_name: str, state: str) -> list[str]:
    return _build_dba_queries(business_name, state)


def build_out_of_state_queries(business_name: str) -> list[str]:
    return _build_out_of_state_queries(business_name)
