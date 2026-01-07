from urllib.parse import urlparse

import requests

from ai_agent.settings import Settings


def extract_domain(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.netloc:
        return parsed.netloc.lower()
    if parsed.path and "." in parsed.path:
        return parsed.path.split("/")[0].lower()
    return None


def is_federal_domain(domain: str | None, settings: Settings) -> bool | None:
    if not domain:
        return None

    try:
        resp = requests.get(
            "https://api.gsa.gov/technology/site-scanning/v1/websites",
            params={"target_url_domain": domain},
            headers={"x-api-key": settings.gsa_site_scanning_api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception:
        return None

    if isinstance(data.get("data"), list) and data["data"]:
        return True
    count = data.get("count")
    if isinstance(count, int):
        return count > 0
    return False
