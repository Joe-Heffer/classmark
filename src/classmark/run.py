"""Run a question set over sampled records with one backend.

For each record: build (or reuse) the profile state, build one request holding
every question, then answer it from the cache or by calling the backend.
Results go to ``results/<experiment>/<backend>.jsonl`` and every request is
written to the audit log in ``logs/``.

Spending is capped: before each uncached call, a pessimistic cost estimate is
reserved against the budget, and the run stops before any call that could
exceed it. ``--dry-run`` builds states and requests but calls no model API.
"""

import hashlib
import json
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

from classmark import config
from classmark.backends import get_backend
from classmark.profile import Profile, profile_record
from classmark.questions import load_question_set
from classmark.sample import load_records
from classmark.sources import PoliteClient
from classmark.store import AuditLog, Cache, request_key


class Budget:
    """Reserve an estimate before a call, then settle it with the actual cost."""

    def __init__(self, limit_usd: float):
        self.limit = limit_usd
        self.spent = 0.0
        self.reserved = 0.0
        self._lock = threading.Lock()

    def reserve(self, estimate: float) -> bool:
        with self._lock:
            if self.spent + self.reserved + estimate > self.limit:
                return False
            self.reserved += estimate
            return True

    def settle(self, estimate: float, actual: float) -> None:
        with self._lock:
            self.reserved -= estimate
            self.spent += actual


def git_commit() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_or_build_state(record: dict, experiment: str, exclude: list[str], client: PoliteClient) -> Profile:
    """Profiles are cached in data/<experiment>/states/ so files are fetched once."""
    path = config.DATA_DIR / experiment / "states" / f"{record['zenodo_id']}.json"
    if path.exists():
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved["meta"].get("exclude") == list(exclude):
            return Profile(**saved)
    profile = profile_record(record, client, exclude=exclude)
    profile.meta["exclude"] = list(exclude)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"state": profile.state, "meta": profile.meta}, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return profile


def run(
    experiment: str,
    backend_name: str,
    n: int | None = None,
    budget_usd: float = config.DEFAULT_BUDGET_USD,
    dry_run: bool = False,
    reverse_options: bool = False,
    workers: int = 4,
) -> Path:
    qs = load_question_set(experiment)
    exp = qs.experiment
    records = load_records(exp)[:n] if n else load_records(exp)
    backend = get_backend(backend_name)
    questions = qs.all_questions(reverse_options=reverse_options)
    variant = backend_name + ("-reversed" if reverse_options else "")
    started = datetime.now(UTC)
    run_id = f"{started:%Y%m%dT%H%M%SZ}_{exp}_{variant}" + ("_dryrun" if dry_run else "")
    qs_file = next(config.QUESTIONS_DIR.glob(f"{exp}*.yaml"))

    print(f"Profiling {len(records)} records (cached in data/{exp}/states/)")
    http = PoliteClient()
    states = {r["doi"]: load_or_build_state(r, exp, qs.exclude_from_state, http) for r in records}

    log = AuditLog(run_id)
    log.write(
        {
            "event": "run_start",
            "run_id": run_id,
            "experiment": exp,
            "backend": backend.name,
            "model": backend.model,
            "settings": backend.settings(),
            "records": len(records),
            "budget_usd": budget_usd,
            "dry_run": dry_run,
            "reverse_options": reverse_options,
            "question_set": qs_file.relative_to(config.ROOT).as_posix(),
            "question_set_sha256": hashlib.sha256(qs_file.read_bytes()).hexdigest(),
            "git_commit": git_commit(),
        }
    )

    requests = []
    for r in records:
        payload = backend.build_request(states[r["doi"]].state, questions)
        key = request_key(backend.name, backend.model, backend.settings(), payload)
        requests.append((r, payload, key))

    if dry_run:
        out = config.RESULTS_DIR / exp / "dryrun" / f"{variant}.jsonl"
        out.parent.mkdir(parents=True, exist_ok=True)
        total = 0.0
        with out.open("w", encoding="utf-8") as f:
            for r, payload, key in requests:
                tin, tout = backend.estimate_tokens(payload)
                est = backend.cost(tin, tout)
                total += est
                f.write(
                    json.dumps(
                        {
                            "doi": r["doi"],
                            "key": key,
                            "estimated_input_tokens": tin,
                            "estimated_max_output_tokens": tout,
                            "estimated_max_cost_usd": est,
                            "state_meta": states[r["doi"]].meta,
                            "payload": payload,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
        log.write({"event": "dry_run", "requests": len(requests), "estimated_max_cost_usd": total})
        print(f"Dry run: {len(requests)} requests written to {out}")
        print(f"Estimated worst-case cost: ${total:.4f} (budget ${budget_usd:.2f}). No model API was called.")
        return out

    cache = Cache(backend.name)
    budget = Budget(budget_usd)
    stop = threading.Event()

    def answer(r: dict, payload: dict, key: str) -> dict:
        base = {"doi": r["doi"], "key": key, "labels": r["labels"], "noise_flags": r["noise_flags"]}
        hit = cache.get(key)
        if hit:
            log.write(
                {
                    "event": "request",
                    "cached": True,
                    "doi": r["doi"],
                    "key": key,
                    "model": hit["response"]["model"],
                    "request_id": hit["response"]["request_id"],
                }
            )
            return {**base, **hit["response"], "cached": True}
        if stop.is_set():
            return {**base, "skipped": "budget"}
        tin, tout = backend.estimate_tokens(payload)
        estimate = backend.cost(tin, tout)
        if not budget.reserve(estimate):
            stop.set()
            log.write(
                {
                    "event": "budget_stop",
                    "doi": r["doi"],
                    "spent_usd": budget.spent,
                    "estimate_usd": estimate,
                    "budget_usd": budget.limit,
                }
            )
            return {**base, "skipped": "budget"}
        try:
            resp = backend.call(payload, questions)
        except Exception as e:
            budget.settle(estimate, 0.0)
            log.write(
                {"event": "error", "doi": r["doi"], "key": key, "payload": payload, "error": f"{type(e).__name__}: {e}"}
            )
            return {**base, "error": f"{type(e).__name__}: {e}"}
        cost = backend.cost(resp.input_tokens, resp.output_tokens)
        budget.settle(estimate, cost)
        record = {
            "answers": resp.answers,
            "model": resp.model,
            "input_tokens": resp.input_tokens,
            "output_tokens": resp.output_tokens,
            "latency_s": resp.latency_s,
            "request_id": resp.request_id,
            "cost_usd": cost,
            "diagnostics": resp.diagnostics,
        }
        if resp.answers:  # never cache a failed answer
            cache.put(
                key,
                {
                    "backend": backend.name,
                    "payload": payload,
                    "response": record,
                    "raw": resp.raw,
                    "answered_at": datetime.now(UTC).isoformat(),
                },
            )
        log.write(
            {
                "event": "request",
                "cached": False,
                "doi": r["doi"],
                "key": key,
                "payload": payload,
                "response": resp.raw,
                **record,
            }
        )
        if not resp.answers:
            return {**base, **record, "error": resp.diagnostics.get("error", "no answers")}
        return {**base, **record, "cached": False}

    results = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(answer, *req) for req in requests]
        for i, fut in enumerate(as_completed(futures), 1):
            results.append(fut.result())
            if i % 10 == 0 or i == len(futures):
                print(f"  {i}/{len(futures)} done, ${budget.spent:.4f} spent")

    order = {r["doi"]: i for i, (r, _, _) in enumerate(requests)}
    results.sort(key=lambda x: order[x["doi"]])
    out = config.RESULTS_DIR / exp / f"{variant}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for res in results:
            f.write(json.dumps(res, ensure_ascii=False) + "\n")

    summary = {
        "event": "run_end",
        "answered": sum(1 for x in results if "answers" in x and x["answers"]),
        "cached": sum(1 for x in results if x.get("cached")),
        "errors": sum(1 for x in results if "error" in x),
        "skipped_budget": sum(1 for x in results if x.get("skipped") == "budget"),
        "spent_usd": budget.spent,
    }
    log.write(summary)
    print(
        f"{summary['answered']} answered ({summary['cached']} from cache), {summary['errors']} errors, "
        f"{summary['skipped_budget']} skipped for budget; ${budget.spent:.4f} spent this run"
    )
    print(f"Results: {out}\nAudit log: {log.path}")
    return out
