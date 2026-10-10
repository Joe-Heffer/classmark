import math

import pytest

from classmark import metrics
from classmark.backends.base import choice_confidence, normalise, score_confidence
from classmark.hierarchy import all_leaf_probabilities, beam_search


def test_accuracy_and_macro_f1():
    y_true = ["a", "a", "b", "c"]
    y_pred = ["a", "b", "b", "a"]
    assert metrics.accuracy(y_true, y_pred) == 0.5
    # a: tp1 fp1 fn1 -> 0.5; b: tp1 fp1 fn0 -> 2/3; c: tp0 fp0 fn1 -> 0
    assert metrics.macro_f1(y_true, y_pred) == pytest.approx((0.5 + 2 / 3 + 0) / 3)


def test_top_k():
    probs = [{"a": 0.5, "b": 0.3, "c": 0.2}, {"a": 0.6, "b": 0.3, "c": 0.1}]
    assert metrics.top_k_accuracy(["c", "b"], probs, 1) == 0.0
    assert metrics.top_k_accuracy(["c", "b"], probs, 2) == 0.5
    assert metrics.top_k_accuracy(["c", "b"], probs, 3) == 1.0


def test_ece_perfectly_calibrated_is_zero():
    conf = [0.8] * 10
    correct = [True] * 8 + [False] * 2
    assert metrics.expected_calibration_error(conf, correct) == pytest.approx(0.0)


def test_ece_hand_computed():
    # Two bins: 0.9 conf with 50% accuracy (gap 0.4), 0.3 conf with 50% accuracy (gap 0.2).
    conf = [0.9, 0.9, 0.3, 0.3]
    correct = [True, False, True, False]
    assert metrics.expected_calibration_error(conf, correct, n_bins=10) == pytest.approx(0.3)


def test_reliability_bins_include_one():
    bins = metrics.reliability_bins([1.0, 0.0], [True, False], n_bins=4)
    assert bins[-1]["count"] == 1 and bins[0]["count"] == 1


def test_coverage_curve_and_target():
    conf = [0.99, 0.95, 0.9, 0.6, 0.5]
    correct = [True, True, False, True, False]
    curve = metrics.coverage_curve(conf, correct)
    assert [p["coverage"] for p in curve] == [0.2, 0.4, 0.6, 0.8, 1.0]
    assert curve[2]["accuracy"] == pytest.approx(2 / 3)
    best = metrics.coverage_at_accuracy(conf, correct, 0.95)
    assert best["coverage"] == 0.4 and best["threshold"] == 0.95


def test_coverage_ties_are_accepted_together():
    curve = metrics.coverage_curve([0.9, 0.9, 0.5], [True, False, True])
    assert curve[0] == {"threshold": 0.9, "coverage": pytest.approx(2 / 3), "accuracy": 0.5}


def test_coverage_none_reaches_target():
    assert metrics.coverage_at_accuracy([0.9, 0.8], [False, False], 0.95)["coverage"] == 0.0


def test_choice_confidence_matches_jev_formula():
    assert choice_confidence({"a": 1.0, "b": 0.0, "c": 0.0}) == 1.0
    assert choice_confidence({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}) == pytest.approx(0.0)
    # Example from the TypeSafe docs: 0.61 top probability over three options -> 0.415.
    assert choice_confidence({"a": 0.61, "b": 0.35, "c": 0.04}) == pytest.approx(0.415)


def test_score_confidence():
    assert score_confidence([0, 0, 1, 0, 0]) == 1.0
    assert score_confidence([0.2] * 5) == 0.0
    # Probability next to the peak lowers confidence less than probability far away.
    assert score_confidence([0, 0.5, 0.5, 0, 0]) > score_confidence([0.5, 0, 0, 0, 0.5])


def test_normalise_reports_raw_sum():
    probs, raw = normalise({"a": 0.6, "b": 0.6})
    assert probs == {"a": 0.5, "b": 0.5} and raw == pytest.approx(1.2)
    probs, raw = normalise({"a": 0.0, "b": 0.0})
    assert probs == {"a": 0.5, "b": 0.5} and raw == 0


ANSWERS = {
    "fos": {"probabilities": {"Nat": 0.55, "Eng": 0.45}},
    "fos > Nat": {"probabilities": {"Maths": 0.5, "Physics": 0.5}},
    "fos > Eng": {"probabilities": {"Civil": 0.95, "Mech": 0.05}},
}


def test_beam_search_recovers_from_greedy_mistake():
    paths = beam_search(ANSWERS, "fos", width=3)
    # Greedy would take Nat (0.55) then a 0.5 coin flip; beam prefers Eng > Civil.
    assert paths[0]["path"] == ["Eng", "Civil"]
    assert paths[0]["score"] == pytest.approx(math.sqrt(0.45 * 0.95))
    assert paths[0]["joint_probability"] == pytest.approx(0.45 * 0.95)
    assert len(paths) == 3


def test_beam_width_one_is_greedy():
    paths = beam_search(ANSWERS, "fos", width=1)
    assert paths[0]["path"][0] == "Nat"


def test_leaf_probabilities_sum_to_one():
    leaves = all_leaf_probabilities(ANSWERS, "fos")
    assert sum(leaves.values()) == pytest.approx(1.0)
    assert leaves[("Eng", "Civil")] == pytest.approx(0.4275)
