"""Evaluation metrics. Pure functions on plain lists, so they are easy to test."""

from collections.abc import Sequence

import numpy as np


def accuracy(y_true: Sequence, y_pred: Sequence) -> float:
    if not y_true:
        return float("nan")
    return float(np.mean([t == p for t, p in zip(y_true, y_pred, strict=True)]))


def macro_f1(y_true: Sequence, y_pred: Sequence, labels: Sequence | None = None) -> float:
    """Unweighted mean F1 over classes.

    By default the classes are those that appear in the gold labels. A
    prediction of a class that never occurs in the gold labels counts as a miss
    for the item's gold class but does not add a class of its own.
    """
    if not y_true:
        return float("nan")
    labels = list(dict.fromkeys(labels if labels is not None else y_true))
    f1s = []
    for c in labels:
        tp = sum(t == c and p == c for t, p in zip(y_true, y_pred))
        fp = sum(t != c and p == c for t, p in zip(y_true, y_pred))
        fn = sum(t == c and p != c for t, p in zip(y_true, y_pred))
        denom = 2 * tp + fp + fn
        f1s.append(2 * tp / denom if denom else 0.0)
    return float(np.mean(f1s))


def top_k_accuracy(y_true: Sequence, probabilities: Sequence[dict[str, float]], k: int) -> float:
    """Share of items whose gold label is among the k most probable options."""
    if not y_true:
        return float("nan")
    hits = []
    for t, probs in zip(y_true, probabilities, strict=True):
        ranked = sorted(probs, key=probs.get, reverse=True)[:k]
        hits.append(t in ranked)
    return float(np.mean(hits))


def reliability_bins(confidence: Sequence[float], correct: Sequence[bool], n_bins: int = 15) -> list[dict]:
    """Equal-width bins on [0, 1]; the last bin includes 1.0."""
    conf = np.asarray(confidence, dtype=float)
    corr = np.asarray(correct, dtype=float)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(conf, edges[1:-1], right=True), 0, n_bins - 1)
    bins = []
    for b in range(n_bins):
        mask = idx == b
        bins.append({
            "lower": float(edges[b]), "upper": float(edges[b + 1]), "count": int(mask.sum()),
            "mean_confidence": float(conf[mask].mean()) if mask.any() else None,
            "accuracy": float(corr[mask].mean()) if mask.any() else None,
        })
    return bins


def expected_calibration_error(confidence: Sequence[float], correct: Sequence[bool], n_bins: int = 15) -> float:
    """ECE: the count-weighted mean gap between confidence and accuracy across bins.

    ``confidence`` is the probability given to the predicted label (top-label ECE).
    """
    n = len(confidence)
    if n == 0:
        return float("nan")
    return float(sum(
        b["count"] / n * abs(b["accuracy"] - b["mean_confidence"])
        for b in reliability_bins(confidence, correct, n_bins) if b["count"]
    ))


def brier_binary(probability: Sequence[float], outcome: Sequence[bool]) -> float:
    p = np.asarray(probability, dtype=float)
    y = np.asarray(outcome, dtype=float)
    return float(np.mean((p - y) ** 2)) if len(p) else float("nan")


def coverage_curve(confidence: Sequence[float], correct: Sequence[bool]) -> list[dict]:
    """Accept every item with confidence >= t, for each distinct t (highest first).

    Each point gives the threshold, the share of items accepted (coverage) and
    the accuracy among them. Ties are accepted together, as a threshold would.
    """
    conf = np.asarray(confidence, dtype=float)
    corr = np.asarray(correct, dtype=float)
    n = len(conf)
    points = []
    for t in sorted(set(conf.tolist()), reverse=True):
        mask = conf >= t
        points.append({"threshold": t, "coverage": float(mask.sum() / n),
                       "accuracy": float(corr[mask].mean())})
    return points


def coverage_at_accuracy(confidence: Sequence[float], correct: Sequence[bool], target: float = 0.95) -> dict:
    """The largest coverage whose accepted set reaches ``target`` accuracy.

    Returns coverage 0 and threshold None when no threshold reaches the target.
    This is measured on the evaluation sample itself; a deployed threshold
    would need choosing on held-out data.
    """
    best = {"coverage": 0.0, "threshold": None, "accuracy": None}
    for p in coverage_curve(confidence, correct):
        if p["accuracy"] >= target and p["coverage"] > best["coverage"]:
            best = p
    return best
