"""Response cache and audit log.

Every request is keyed by a SHA-256 hash of everything that determines its
answer: backend, model, backend settings, state and questions. Responses are
stored once in ``cache/<backend>.jsonl``, so the same request is never sent
twice (Blueprint C17).

Every lookup, cached or not, is also appended to ``logs/<run_id>.jsonl``: the
request, the response, model version, request id, tokens, latency and estimated
cost. This audit log is the traceability record (Blueprint P5, R10, C13).
"""

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from classmark import config


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def request_key(backend: str, model: str, settings: dict, payload: dict) -> str:
    material = {"backend": backend, "model": model, "settings": settings, "payload": payload}
    return hashlib.sha256(canonical(material).encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, backend: str, directory: Path = None):
        directory = directory or config.CACHE_DIR
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{backend}.jsonl"
        self._lock = threading.Lock()
        self._entries: dict[str, dict] = {}
        if self.path.exists():
            with self.path.open(encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        entry = json.loads(line)
                        self._entries[entry["key"]] = entry

    def get(self, key: str) -> dict | None:
        return self._entries.get(key)

    def put(self, key: str, entry: dict) -> None:
        entry = {"key": key, **entry}
        with self._lock:
            self._entries[key] = entry
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AuditLog:
    def __init__(self, run_id: str, directory: Path = None):
        directory = directory or config.LOG_DIR
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"{run_id}.jsonl"
        self._lock = threading.Lock()

    def write(self, event: dict) -> None:
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"logged_at": now(), **event}, ensure_ascii=False) + "\n")
