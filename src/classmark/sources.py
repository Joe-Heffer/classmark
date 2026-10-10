"""Read-only access to the public Zenodo and DataCite REST APIs.

Only public records and open files are fetched. Nothing is ever sent to these
services beyond search queries.
"""

import html
import re
import time
from html.parser import HTMLParser

import httpx

from classmark import config

DATACITE_API = "https://api.datacite.org/dois"
ZENODO_API = "https://zenodo.org/api/records"
ZENODO_CLIENT_ID = "cern.zenodo"


class PoliteClient:
    """An httpx client that backs off on 429/5xx and spaces out requests."""

    def __init__(self, min_interval: float = 0.5, retries: int = 5):
        self.http = httpx.Client(
            headers={"User-Agent": config.USER_AGENT},
            timeout=config.HTTP_TIMEOUT,
            follow_redirects=True,
        )
        self.min_interval = min_interval
        self.retries = retries
        self._last = 0.0

    def get(self, url: str, **kwargs) -> httpx.Response:
        for attempt in range(self.retries):
            wait = self.min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            r = self.http.get(url, **kwargs)
            if r.status_code == 429 or r.status_code >= 500:
                delay = float(r.headers.get("retry-after", 2 ** (attempt + 1)))
                time.sleep(min(delay, 60))
                continue
            return r
        r.raise_for_status()
        return r

    def get_json(self, url: str, **kwargs) -> dict:
        r = self.get(url, **kwargs)
        r.raise_for_status()
        return r.json()

    def get_range(self, url: str, n_bytes: int) -> bytes:
        """Fetch the first ``n_bytes`` of a file, so large files are never downloaded whole."""
        r = self.get(url, headers={"Range": f"bytes=0-{n_bytes - 1}"})
        r.raise_for_status()
        return r.content[:n_bytes]


def datacite_search(
    client: PoliteClient, query: str, n: int, random: bool = True
) -> list[dict]:
    """Return up to ``n`` DataCite DOI records for a Lucene query on Zenodo DOIs."""
    params = {
        "query": query,
        "client-id": ZENODO_CLIENT_ID,
        "page[size]": min(n, 1000),
        "disable-facets": "true",
    }
    if random:
        params["random"] = "true"
    return client.get_json(DATACITE_API, params=params)["data"]


def zenodo_record_id(doi: str) -> str | None:
    """The Zenodo record id in a version DOI such as 10.5281/zenodo.1234567."""
    m = re.fullmatch(r"10\.5281/zenodo\.(\d+)", doi.lower())
    return m.group(1) if m else None


def zenodo_record(client: PoliteClient, record_id: str) -> dict | None:
    r = client.get(f"{ZENODO_API}/{record_id}")
    if r.status_code in (404, 410):
        return None
    r.raise_for_status()
    return r.json()


class _TextExtractor(HTMLParser):
    BLOCK = {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "tr"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)


def html_to_text(s: str) -> str:
    """Strip HTML from a Zenodo description, keeping paragraph breaks."""
    p = _TextExtractor()
    p.feed(s or "")
    text = html.unescape("".join(p.parts))
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()
