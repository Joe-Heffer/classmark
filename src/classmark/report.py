"""Evaluate results and write a Markdown report with PNG plots to ``reports/<experiment>/``."""

import json
import math
import statistics
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from classmark import config, metrics  # noqa: E402
from classmark.hierarchy import beam_search  # noqa: E402
from classmark.questions import QuestionSet, load_question_set  # noqa: E402
from classmark.sample import fos_vocabulary, load_handcheck, load_records, norm  # noqa: E402

# Default dataviz palette, categorical slots 1 and 2 (validated as a pair), plus
# a distinct marker per backend so identity never relies on colour alone.
STYLE = {
    "jev": {"color": "#2a78d6", "marker": "o", "label": "Jev"},
    "claude": {"color": "#eb6834", "marker": "s", "label": "Claude"},
}
INK, MUTED, GRID, SURFACE = "#0b0b0b", "#898781", "#e1e0d9", "#fcfcfb"


# --- Turning results into scored items ------------------------------------------


def load_results(exp: str) -> dict[str, list[dict]]:
    out = {}
    for path in sorted((config.RESULTS_DIR / exp).glob("*.jsonl")):
        with path.open(encoding="utf-8") as f:
            out[path.stem] = [json.loads(line) for line in f if line.strip()]
    return out


def argmax(probs: dict[str, float]) -> str:
    return max(probs, key=probs.get)


def e1_items(results: list[dict], qs: QuestionSet, handcheck: dict[str, str]) -> dict[str, list[dict]]:
    qid = next(iter(qs.questions))
    items = []
    for r in results:
        if not r.get("answers"):
            continue
        probs = r["answers"][qid]["probabilities"]
        pred = argmax(probs)
        gold = r["labels"][qs.label]
        items.append(
            {
                "doi": r["doi"],
                "gold": {gold},
                "gold_primary": gold,
                "pred": pred,
                "p": probs[pred],
                "ranked": sorted(probs, key=probs.get, reverse=True),
                "flags": r["noise_flags"],
                "checked": handcheck.get(r["doi"]),
            }
        )
    return {"resource type": items}


def parse_fos(text: str, qs: QuestionSet) -> tuple[set[str], set[str]]:
    """Parse a hand-checked FoS label: names separated by ';', subfields or broad fields."""
    tops, parent_of = fos_vocabulary(qs)
    subs_by_norm = {norm(c): c for node in qs.hierarchy.options.values() for c in (node.children or {})}
    top_set, sub_set = set(), set()
    for part in text.split(";"):
        n = norm(part.split(">")[-1])
        if n in tops:
            top_set.add(tops[n])
        elif n in parent_of:
            sub_set.add(subs_by_norm[n])
            top_set.add(parent_of[n])
    return top_set, sub_set


def e2_items(results: list[dict], qs: QuestionSet, handcheck: dict[str, str]) -> dict[str, list[dict]]:
    root = qs.hierarchy.id
    _, parent_of = fos_vocabulary(qs)
    subs_by_norm = {norm(c): c for node in qs.hierarchy.options.values() for c in (node.children or {})}
    top_items, sub_items = [], []
    for r in results:
        if not r.get("answers"):
            continue
        fos = r["labels"]["fos"]
        gold_top = set(fos["top"])
        gold_sub = {subs_by_norm[norm(s)] for s in fos["sub"]}
        checked = handcheck.get(r["doi"])
        checked_top, checked_sub = parse_fos(checked, qs) if checked else (None, None)

        top_probs = r["answers"][root]["probabilities"]
        pred_top = argmax(top_probs)
        paths = beam_search(r["answers"], root, width=config.BEAM_WIDTH)
        best = paths[0]
        greedy_top = pred_top
        greedy_sub = argmax(r["answers"][f"{root} > {greedy_top}"]["probabilities"])
        common = {"doi": r["doi"], "flags": r["noise_flags"]}
        if gold_top:
            top_items.append(
                {
                    **common,
                    "gold": gold_top,
                    "gold_primary": sorted(gold_top)[0],
                    "pred": pred_top,
                    "p": top_probs[pred_top],
                    "ranked": sorted(top_probs, key=top_probs.get, reverse=True),
                    "checked": checked_top,
                }
            )
        if gold_sub:
            sub_items.append(
                {
                    **common,
                    "gold": gold_sub,
                    "gold_primary": sorted(gold_sub)[0],
                    "pred": best["path"][-1],
                    "p": best["joint_probability"],
                    "ranked": [p["path"][-1] for p in paths],
                    "checked": checked_sub,
                    "beam_path": best["path"],
                    "greedy_pred": greedy_sub,
                    "beam_differs_from_greedy": best["path"][-1] != greedy_sub,
                }
            )
    return {"broad field": top_items, "subfield": sub_items}


ITEM_BUILDERS = {"e1": e1_items, "e2": e2_items}


def score(items: list[dict], use_checked: bool = False) -> dict:
    """Metrics over items. With ``use_checked``, only hand-checked items, scored against those labels."""
    if use_checked:
        items = [
            {**i, "gold": i["checked"] if isinstance(i["checked"], set) else {i["checked"]}}
            for i in items
            if i.get("checked")
        ]
    if not items:
        return {"n": 0}
    correct = [i["pred"] in i["gold"] for i in items]
    # For macro-F1, credit a prediction that matches any gold label; otherwise use the first gold label.
    y_true = [i["pred"] if i["pred"] in i["gold"] else sorted(i["gold"])[0] for i in items]
    y_pred = [i["pred"] for i in items]
    conf = [i["p"] for i in items]
    cov = metrics.coverage_at_accuracy(conf, correct, config.TARGET_ACCURACY)
    return {
        "n": len(items),
        "accuracy": metrics.accuracy(correct, [True] * len(correct)),
        "macro_f1": metrics.macro_f1(y_true, y_pred),
        "top3": float(sum(bool(set(i["ranked"][:3]) & i["gold"]) for i in items) / len(items)),
        "ece": metrics.expected_calibration_error(conf, correct, config.ECE_BINS),
        "mean_p": statistics.fmean(conf),
        "coverage_at_target": cov["coverage"],
        "threshold_at_target": cov["threshold"],
        "_conf": conf,
        "_correct": correct,
    }


# --- Plots -------------------------------------------------------------------------


def _axes(title: str, xlabel: str, ylabel: str):
    fig, ax = plt.subplots(figsize=(5.2, 5.0), dpi=150)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=INK, labelsize=8)
    ax.grid(color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    ax.set_title(title, color=INK, fontsize=10, loc="left")
    ax.set_xlabel(xlabel, color=INK, fontsize=9)
    ax.set_ylabel(ylabel, color=INK, fontsize=9)
    return fig, ax


def reliability_plot(scores: dict[str, dict], title: str, path: Path) -> None:
    fig, ax = _axes(title, "Probability of the predicted label", "Observed accuracy")
    ax.plot([0, 1], [0, 1], color=MUTED, linewidth=1, linestyle="--", label="Perfect calibration")
    for backend, s in scores.items():
        if not s.get("n"):
            continue
        st = STYLE[backend.split("-")[0]]
        bins = [b for b in metrics.reliability_bins(s["_conf"], s["_correct"], config.ECE_BINS) if b["count"]]
        ax.plot(
            [b["mean_confidence"] for b in bins],
            [b["accuracy"] for b in bins],
            color=st["color"],
            linewidth=2,
            marker=st["marker"],
            markersize=6,
            markeredgecolor=SURFACE,
            markeredgewidth=1.5,
            label=f"{st['label']} (ECE {s['ece']:.3f}, n={s['n']})",
        )
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.02)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left", bbox_to_anchor=(0, -0.16))
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def coverage_plot(scores: dict[str, dict], title: str, path: Path) -> None:
    fig, ax = _axes(title, "Coverage (share auto-accepted)", "Accuracy of accepted items")
    ax.axhline(
        config.TARGET_ACCURACY,
        color=MUTED,
        linewidth=1,
        linestyle="--",
        label=f"{config.TARGET_ACCURACY:.0%} accuracy target",
    )
    for backend, s in scores.items():
        if not s.get("n"):
            continue
        st = STYLE[backend.split("-")[0]]
        curve = sorted(metrics.coverage_curve(s["_conf"], s["_correct"]), key=lambda p: p["coverage"])
        ax.plot(
            [p["coverage"] for p in curve],
            [p["accuracy"] for p in curve],
            color=st["color"],
            linewidth=2,
            marker=st["marker"],
            markersize=4,
            label=st["label"],
        )
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.02)
    ax.legend(frameon=False, fontsize=8, labelcolor=INK, loc="upper left", bbox_to_anchor=(0, -0.16))
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


# --- Report ------------------------------------------------------------------------


def fmt(x, pct: bool = False, digits: int = 3) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "–"
    return f"{x:.0%}" if pct else f"{x:.{digits}f}"


def cost_rows(results: list[dict]) -> dict:
    answered = [r for r in results if r.get("answers")]
    if not answered:
        return {}
    return {
        "records": len(answered),
        "model": sorted({r["model"] for r in answered}),
        "latency": statistics.median(r["latency_s"] for r in answered),
        "in_tokens": statistics.fmean(r["input_tokens"] for r in answered),
        "out_tokens": statistics.fmean(r["output_tokens"] for r in answered),
        "cost": statistics.fmean(r["cost_usd"] for r in answered),
        "errors": sum(1 for r in results if "error" in r),
    }


def position_bias(normal: list[dict], reversed_: list[dict], level_items) -> dict[str, float]:
    """Share of records whose prediction is unchanged when option order is reversed."""
    out = {}
    a, b = level_items(normal), level_items(reversed_)
    for level in a:
        pa = {i["doi"]: i["pred"] for i in a[level]}
        pb = {i["doi"]: i["pred"] for i in b.get(level, [])}
        shared = pa.keys() & pb.keys()
        if shared:
            out[level] = sum(pa[d] == pb[d] for d in shared) / len(shared)
    return out


def build_report(experiment: str) -> Path:
    qs = load_question_set(experiment)
    exp = qs.experiment
    key = exp.split("_")[0]
    builder = ITEM_BUILDERS[key]
    results = load_results(exp)
    if not results:
        raise FileNotFoundError(f"no results in {config.RESULTS_DIR / exp}; run the experiment first")
    records = {r["doi"]: r for r in load_records(exp)}
    handcheck = load_handcheck(exp)
    out_dir = config.REPORTS_DIR / exp
    out_dir.mkdir(parents=True, exist_ok=True)

    backends = [b for b in results if not b.endswith("-reversed")]
    items = {b: builder(results[b], qs, handcheck) for b in backends}
    levels = list(next(iter(items.values())).keys())

    lines = [
        f"# {exp.upper().split('_')[0]}: {qs.title}",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from `results/{exp}/`. "
        f"Question set: `questions/{exp}.yaml`. Records sampled: {len(records)} "
        f"(see `data/{exp}/query.json`). Hand-checked labels available: {len(handcheck)}.",
        "",
        "Every prediction is the most probable option. *p* is the probability given to the predicted "
        "label: for a single Choice that is the top probability; for the hierarchy it is the joint "
        "probability P(field) × P(subfield | field) of the best beam-search path. Jev's own "
        "`confidence` is a fixed function of the top probability and the number of options, so it "
        "ranks items in the same order as *p* and is not used separately.",
        "",
    ]

    for level in levels:
        lines += [f"## {level.capitalize()}", ""]
        table = [
            "| System | Subset | n | Accuracy | Macro-F1 | Top-3 | ECE | Mean p | "
            f"Coverage at {config.TARGET_ACCURACY:.0%} | Threshold |",
            "| - | - | -: | -: | -: | -: | -: | -: | -: | -: |",
        ]
        full_scores = {}
        for b in backends:
            lv = items[b][level]
            subsets = {
                "all": score(lv),
                "no noise flags": score([i for i in lv if not i["flags"]]),
                "hand-checked": score(lv, use_checked=True),
            }
            full_scores[b] = subsets["all"]
            for name, s in subsets.items():
                if not s["n"]:
                    table.append(f"| {b} | {name} | 0 | – | – | – | – | – | – | – |")
                    continue
                table.append(
                    f"| {b} | {name} | {s['n']} | {fmt(s['accuracy'], True)} | {fmt(s['macro_f1'])} | "
                    f"{fmt(s['top3'], True)} | {fmt(s['ece'])} | {fmt(s['mean_p'])} | "
                    f"{fmt(s['coverage_at_target'], True)} | {fmt(s['threshold_at_target'])} |"
                )
        slug = level.replace(" ", "_")
        reliability_plot(full_scores, f"Reliability: {level}", out_dir / f"reliability_{slug}.png")
        coverage_plot(full_scores, f"Coverage vs accuracy: {level}", out_dir / f"coverage_{slug}.png")
        lines += table + [
            "",
            f"*Coverage at {config.TARGET_ACCURACY:.0%}* is the largest share of records that could be "
            f"auto-accepted, by thresholding *p*, while the accepted records stay at least "
            f"{config.TARGET_ACCURACY:.0%} accurate. The threshold is chosen on this same sample, so it "
            "is optimistic; a deployed threshold must be set on held-out data.",
            "",
            f"![Reliability diagram]({f'reliability_{slug}.png'})",
            f"![Coverage against accuracy]({f'coverage_{slug}.png'})",
            "",
        ]
        if level == "subfield":
            for b in backends:
                lv = items[b][level]
                differs = sum(i["beam_differs_from_greedy"] for i in lv)
                lines.append(
                    f"* {b}: beam search (width {config.BEAM_WIDTH}) chose a different "
                    f"subfield from greedy search for {differs} of {len(lv)} records."
                )
            lines.append("")

        lines += [f"### Most confident errors: {level}", ""]
        for b in backends:
            errors = sorted((i for i in items[b][level] if i["pred"] not in i["gold"]), key=lambda i: -i["p"])[
                : config.CONFIDENT_ERRORS_SHOWN
            ]
            lines += [
                f"**{b}**",
                "",
                "| p | Predicted | Depositor label | Record | Noise flags |",
                "| -: | - | - | - | - |",
            ]
            for i in errors:
                title = records.get(i["doi"], {}).get("title", "")[:70].replace("|", "/")
                url = records.get(i["doi"], {}).get("url") or f"https://doi.org/{i['doi']}"
                lines.append(
                    f"| {i['p']:.2f} | {i['pred']} | {'; '.join(sorted(i['gold']))} | "
                    f"[{title}]({url}) | {', '.join(i['flags']) or '–'} |"
                )
            if not errors:
                lines.append("| – | – | – | – | – |")
            lines.append("")

    lines += [
        "## Latency, tokens and cost",
        "",
        "| System | Model | Records | Median latency (s) | Mean input tokens | Mean output tokens | "
        "Mean cost per record (US$) | Cost per 1,000 records (US$) | Errors |",
        "| - | - | -: | -: | -: | -: | -: | -: | -: |",
    ]
    for b in backends:
        c = cost_rows(results[b])
        if c:
            lines.append(
                f"| {b} | {', '.join(c['model'])} | {c['records']} | {c['latency']:.2f} | "
                f"{c['in_tokens']:.0f} | {c['out_tokens']:.0f} | {c['cost']:.6f} | "
                f"{c['cost'] * 1000:.3f} | {c['errors']} |"
            )
    lines += [
        "",
        "Latency is the wall-clock time of the original API call (cached answers keep the latency "
        "of the call that produced them). Costs use list prices in `classmark/config.py`. Claude's "
        "output tokens include its (hidden) adaptive thinking. Neither API reports energy use, so "
        "token counts are the only available proxy for environmental impact (Blueprint P14).",
        "",
    ]

    reversed_runs = [b for b in results if b.endswith("-reversed")]
    if reversed_runs:
        lines += [
            "## Option-order sensitivity",
            "",
            "Share of records whose prediction is unchanged when Choice options are given in reverse order.",
            "",
        ]
        for rb in reversed_runs:
            base = rb.removesuffix("-reversed")
            if base in results:
                agree = position_bias(results[base], results[rb], lambda rs: builder(rs, qs, handcheck))
                lines += [f"* {base}: " + ", ".join(f"{lvl} {v:.0%}" for lvl, v in agree.items())]
        lines.append("")

    diag = [r.get("diagnostics", {}) for r in results.get("claude", []) if r.get("answers")]
    stated = [d["stated_matches_argmax"] for dd in diag for d in dd.values() if "stated_matches_argmax" in d]
    sums = [d["raw_probability_sum"] for dd in diag for d in dd.values() if "raw_probability_sum" in d]
    if stated:
        lines += [
            "## Baseline diagnostics",
            "",
            f"* Claude's stated label matched the most probable option in its own distribution in "
            f"{sum(stated)}/{len(stated)} answers.",
            f"* Raw probability sums before rescaling: median {statistics.median(sums):.3f}, "
            f"range {min(sums):.3f}–{max(sums):.3f}.",
            "",
        ]

    flagged = sum(1 for r in records.values() if r["noise_flags"])
    lines += [
        "## Label noise",
        "",
        f"{flagged} of {len(records)} sampled records have at least one noise flag (heuristics in "
        "`classmark/sample.py`). Gold labels are what depositors entered, so some 'errors' above "
        "will be label errors. Fill in `checked_label` in "
        f"`data/{exp}/handcheck.csv` and re-run the report to score against checked labels.",
        "",
    ]
    path = out_dir / "report.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
