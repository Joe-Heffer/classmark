"""End-to-end check that reports build from synthetic results (no network, no APIs)."""

import json
import random

import pytest

from classmark import config
from classmark.questions import load_question_set


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    for name in ("DATA_DIR", "RESULTS_DIR", "REPORTS_DIR"):
        monkeypatch.setattr(config, name, tmp_path / name.lower())
    return tmp_path


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def fake_result(doi, labels, answers, rng):
    return {
        "doi": doi,
        "labels": labels,
        "noise_flags": [],
        "answers": answers,
        "model": "m",
        "input_tokens": 100,
        "output_tokens": 10,
        "latency_s": rng.random(),
        "cost_usd": 1e-5,
        "cached": False,
        "diagnostics": {},
    }


def dist(options, rng, favour=None):
    w = {o: rng.random() + (3 if o == favour else 0) for o in options}
    s = sum(w.values())
    return {o: v / s for o, v in w.items()}


def test_e1_report(workspace):
    from classmark.report import build_report

    rng = random.Random(0)
    qs = load_question_set("e1")
    options = list(qs.questions["resource_type"].options)
    records, results = [], {"jev": [], "claude": []}
    for i in range(30):
        gold = rng.choice(options[:5])
        records.append(
            {
                "doi": f"d{i}",
                "title": f"Record {i}",
                "url": None,
                "noise_flags": [],
                "labels": {"resource_type_general": gold},
            }
        )
        for b in results:
            probs = dist(options, rng, favour=gold if rng.random() < 0.7 else None)
            results[b].append(
                fake_result(
                    f"d{i}", records[-1]["labels"], {"resource_type": {"type": "choice", "probabilities": probs}}, rng
                )
            )
    write_jsonl(config.DATA_DIR / qs.experiment / "records.jsonl", records)
    for b, rows in results.items():
        write_jsonl(config.RESULTS_DIR / qs.experiment / f"{b}.jsonl", rows)

    path = build_report("e1")
    text = path.read_text(encoding="utf-8")
    assert "## Resource type" in text and "Coverage at 95%" in text
    assert (path.parent / "reliability_resource_type.png").exists()
    assert (path.parent / "coverage_resource_type.png").exists()


def test_e2_report(workspace):
    from classmark.report import build_report

    rng = random.Random(1)
    qs = load_question_set("e2")
    questions = qs.all_questions()
    records, rows = [], []
    for i in range(20):
        top = rng.choice(list(qs.hierarchy.options))
        sub = rng.choice(list(qs.hierarchy.options[top].children))
        labels = {"fos": {"top": [top], "sub": [sub], "raw": [sub], "unrecognised": []}}
        records.append({"doi": f"d{i}", "title": f"R{i}", "url": None, "noise_flags": [], "labels": labels})
        answers = {
            qid: {"type": "choice", "probabilities": dist(list(q.options), rng, favour=top if qid == "fos" else sub)}
            for qid, q in questions.items()
        }
        rows.append(fake_result(f"d{i}", labels, answers, rng))
    write_jsonl(config.DATA_DIR / qs.experiment / "records.jsonl", records)
    write_jsonl(config.RESULTS_DIR / qs.experiment / "jev.jsonl", rows)

    text = build_report("e2").read_text(encoding="utf-8")
    assert "## Broad field" in text and "## Subfield" in text
    assert "beam search" in text
