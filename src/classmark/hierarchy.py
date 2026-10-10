"""Beam search over chained Choice probabilities.

Follows TypeSafe's hierarchical classification cookbook: a path's score is the
geometric mean of its edge probabilities,
``product(edge_probabilities) ** (1 / decisions)``, so shallow and deep leaves
are compared fairly. The best ``width`` paths are kept at each level.

The answers come from a single fan-out request, so all child distributions are
already available. ``joint_probability`` (the plain product, that is
P(parent) x P(child | parent)) is also returned: it is a proper probability for
the leaf, which is what calibration needs.
"""

import math

from classmark.questions import HIERARCHY_SEPARATOR


def beam_search(answers: dict[str, dict], root: str, width: int = 3) -> list[dict]:
    """Rank leaf paths from Choice answers keyed ``root``, ``root > A``, ``root > A > B``…

    Returns paths best first, each ``{"path", "score", "joint_probability", "edges"}``.
    """
    beam = [{"path": (), "log_sum": 0.0, "edges": []}]
    finished = []
    while beam:
        expanded = []
        for cand in beam:
            qid = HIERARCHY_SEPARATOR.join((root, *cand["path"]))
            answer = answers.get(qid)
            if answer is None:  # a leaf: no question below it
                finished.append(cand)
                continue
            for option, p in answer["probabilities"].items():
                expanded.append({
                    "path": (*cand["path"], option),
                    "log_sum": cand["log_sum"] + math.log(max(p, 1e-12)),
                    "edges": [*cand["edges"], p],
                })
        pool = sorted(finished + expanded, key=_score, reverse=True)[:width]
        finished = [c for c in pool if not _expandable(c, answers, root)]
        beam = [c for c in pool if _expandable(c, answers, root)]
    ranked = sorted(finished, key=_score, reverse=True)
    return [
        {"path": list(c["path"]), "score": _score(c), "joint_probability": math.prod(c["edges"]),
         "edges": c["edges"]}
        for c in ranked
    ]


def all_leaf_probabilities(answers: dict[str, dict], root: str) -> dict[tuple[str, ...], float]:
    """Joint probability of every leaf, by full enumeration (feasible for shallow taxonomies)."""
    out = {}

    def walk(path: tuple[str, ...], p: float) -> None:
        answer = answers.get(HIERARCHY_SEPARATOR.join((root, *path)))
        if answer is None:
            out[path] = p
            return
        for option, q in answer["probabilities"].items():
            walk((*path, option), p * q)

    walk((), 1.0)
    return out


def _score(c: dict) -> float:
    return math.exp(c["log_sum"] / len(c["edges"])) if c["edges"] else 1.0


def _expandable(c: dict, answers: dict, root: str) -> bool:
    return HIERARCHY_SEPARATOR.join((root, *c["path"])) in answers
