"""Small, auditable source-discovery adapter for body-science topics.

This is intentionally conservative: it uses the public NCBI E-utilities API,
returns source URLs and titles only, and never invents citations. Human review
still decides whether the source actually supports the generated wording.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List

import requests


PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
TIMEOUT_SECONDS = 12


def verify_source_urls(sources: List[Dict[str, str]], max_results: int = 3) -> List[Dict[str, object]]:
    """Check cited URLs without trusting their content or following instructions."""
    checked = []
    for source in (sources or [])[:max_results]:
        url = str((source or {}).get("url", "")).strip()
        item: Dict[str, object] = {"url": url, "ok": False, "status": None}
        if not url.startswith(("https://", "http://")):
            item["error"] = "invalid scheme"
            checked.append(item)
            continue
        try:
            response = requests.head(url, allow_redirects=True, timeout=TIMEOUT_SECONDS)
            if response.status_code in {405, 403}:
                response = requests.get(url, allow_redirects=True, timeout=TIMEOUT_SECONDS, stream=True)
            item["status"] = response.status_code
            item["final_url"] = response.url
            item["ok"] = 200 <= response.status_code < 400
        except requests.RequestException as exc:
            item["error"] = str(exc)[:160]
        checked.append(item)
    return checked


def discover_pubmed_sources(topic: str, max_results: int = 3) -> List[Dict[str, str]]:
    """Return real PubMed records for a topic, or [] on any API failure."""
    query = " ".join(str(topic or "").split()).strip()
    if len(query) < 3:
        return []
    try:
        search = requests.get(
            PUBMED_SEARCH_URL,
            params={"db": "pubmed", "term": query, "retmode": "json", "retmax": max_results},
            timeout=TIMEOUT_SECONDS,
        )
        search.raise_for_status()
        ids = search.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        summary = requests.get(
            PUBMED_SUMMARY_URL,
            params={"db": "pubmed", "id": ",".join(ids[:max_results]), "retmode": "json"},
            timeout=TIMEOUT_SECONDS,
        )
        summary.raise_for_status()
        data = summary.json().get("result", {})
        accessed = datetime.now(timezone.utc).date().isoformat()
        output: List[Dict[str, str]] = []
        for pmid in ids[:max_results]:
            record = data.get(str(pmid)) or {}
            title = " ".join(str(record.get("title", "")).split())
            if not title:
                continue
            output.append({
                "title": title,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "accessed_at": accessed,
                "provider": "pubmed",
                "pmid": str(pmid),
            })
        return output
    except (requests.RequestException, ValueError, TypeError, KeyError):
        return []
