"""
Scrape course data from courses.myskillsfuture.gov.sg.
The portal is Next.js with SSR — course data is embedded in the HTML
as a JSON string inside self.__next_f.push([1,"..."]) script tags.
No headless browser needed; plain requests + json works.
"""
import json
import re
import warnings
from typing import Dict, List, Optional

import requests

warnings.filterwarnings("ignore")  # suppress urllib3 LibreSSL warning

PORTAL_BASE = "https://courses.myskillsfuture.gov.sg"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _get(url: str) -> str:
    resp = SESSION.get(url, timeout=20)
    resp.raise_for_status()
    return resp.text


def _extract_course_data(html: str) -> Optional[Dict]:
    """Extract the embedded Next.js course JSON from a course detail page."""
    scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.DOTALL)
    for script in scripts:
        if "courseRuns" not in script or "courseTitle" not in script:
            continue
        m = re.search(
            r"self\.__next_f\.push\(\[1,\"(.*)\"\]\)\s*$", script, re.DOTALL
        )
        if not m:
            continue
        try:
            decoded = json.loads('"' + m.group(1) + '"')
            return json.loads(decoded)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def _parse_runs(runs_raw: List) -> List:
    """Normalise raw courseRuns to a simple list of dicts."""
    result = []
    for r in runs_raw:
        vacancy_code = r.get("courseVacancyCode", "")
        result.append({
            "run_id": r.get("courseRunId", ""),
            "start_date": r.get("courseStartDate", ""),
            "end_date": r.get("courseEndDate", ""),
            "mode": r.get("modeOfTraining", ""),
            "vacancy": _vacancy_label(vacancy_code),
            "schedule": (r.get("scheduleInfo") or "").strip(),
            "apply_url": r.get("courseApplicationUrl", ""),
        })
    return result


def _vacancy_label(code: str) -> str:
    return {"A": "Available", "F": "Full", "L": "Limited"}.get(code, code)


def _course_links_from_search(html: str) -> List[str]:
    """Return list of /courses/... paths from a search results page."""
    links = re.findall(r'href="(/courses/[^"]+)"', html)
    seen = set()
    unique = []
    for l in links:
        if l not in seen:
            seen.add(l)
            unique.append(l)
    return unique


# ── Public interface ──────────────────────────────────────────────────────────

def search_courses(query: str) -> list[dict]:
    """
    Search for courses matching a keyword or TGS reference number.
    Returns a list of {tgs_ref, title, provider, course_url}.
    """
    html = _get(f"{PORTAL_BASE}/search?q={requests.utils.quote(query)}")
    links = _course_links_from_search(html)
    if not links:
        return []

    results = []
    for path in links[:10]:  # cap at 10 results per search
        tgs_ref = _tgs_from_path(path)
        if not tgs_ref:
            continue
        results.append({
            "tgs_ref": tgs_ref,
            "title": _title_from_path(path),
            "provider": "",
            "course_url": PORTAL_BASE + path,
        })
    return results


def get_course_runs(tgs_ref: str, course_url: str = "") -> dict:
    """
    Fetch run dates for a specific TGS course reference.
    Returns {tgs_ref, title, provider, course_url, runs[]}.
    Runs is empty if no upcoming dates are published.
    """
    if not course_url:
        course_url = _resolve_course_url(tgs_ref)
    if not course_url:
        return {"tgs_ref": tgs_ref, "title": "", "provider": "", "course_url": "", "runs": []}

    html = _get(course_url)
    data = _extract_course_data(html)
    if not data:
        return {"tgs_ref": tgs_ref, "title": "", "provider": "", "course_url": course_url, "runs": []}

    tps = data.get("trainingPartners") or data.get("trainingProviders") or []
    provider = tps[0].get("name", "") if tps else ""

    return {
        "tgs_ref": data.get("courseReferenceNumber", tgs_ref),
        "title": data.get("courseTitle", ""),
        "provider": provider,
        "course_url": course_url,
        "runs": _parse_runs(data.get("courseRuns") or []),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_course_url(tgs_ref: str) -> str:
    """Find the full /courses/TGS-XXX--slug URL for a TGS reference number."""
    html = _get(f"{PORTAL_BASE}/search?q={requests.utils.quote(tgs_ref)}")
    links = _course_links_from_search(html)
    for path in links:
        if tgs_ref.upper() in path.upper():
            return PORTAL_BASE + path
    return ""


def _tgs_from_path(path: str) -> str:
    """Extract TGS-XXXXXXXXXX from a course path like /courses/TGS-12345--title."""
    m = re.search(r"(TGS-\d+)", path, re.IGNORECASE)
    return m.group(1).upper() if m else ""


def _title_from_path(path: str) -> str:
    """Derive a readable title from the URL slug."""
    # /courses/TGS-12345--My-Course-Title  →  My Course Title
    m = re.search(r"TGS-\d+--(.+)$", path, re.IGNORECASE)
    if not m:
        return ""
    return m.group(1).replace("-", " ").title()
