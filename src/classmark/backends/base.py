"""The interface every backend implements, and helpers shared between them.

All backends return answers in one normalised shape, so evaluation code does
not need to know which system produced them:

* choice: ``{"type": "choice", "choice": str, "probabilities": {option: p}, "confidence": c}``
* score:  ``{"type": "score", "score": expected level, "probabilities": {level: p}, "confidence": c}``
* noul:   ``{"type": "noul", "noul": p}``
"""

from dataclasses import dataclass, field

from classmark import config
from classmark.questions import Question


@dataclass
class Response:
    answers: dict[str, dict]
    model: str
    input_tokens: int
    output_tokens: int
    latency_s: float
    request_id: str | None = None
    raw: dict = field(default_factory=dict)
    diagnostics: dict = field(default_factory=dict)


class Backend:
    name: str = ""
    model: str = ""

    def settings(self) -> dict:
        """Settings that affect answers; part of the cache key."""
        return {}

    def build_request(self, state: dict, questions: dict[str, Question]) -> dict:
        """The exact JSON-serialisable payload that will be sent."""
        raise NotImplementedError

    def call(self, payload: dict, questions: dict[str, Question]) -> Response:
        raise NotImplementedError

    def estimate_tokens(self, payload: dict) -> tuple[int, int]:
        """A conservative (input, output) token estimate made before calling."""
        raise NotImplementedError

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        p = config.PRICES[self.name]
        return (input_tokens * p["input"] + output_tokens * p["output"]) / 1_000_000


def choice_confidence(probabilities: dict[str, float]) -> float:
    """Jev's documented Choice confidence: (n * p_max - 1) / (n - 1), clipped to [0, 1].

    It is a function of the top probability and the number of options only.
    """
    n = len(probabilities)
    if n < 2:
        return 1.0
    p_max = max(probabilities.values())
    return max(0.0, min(1.0, (n * p_max - 1) / (n - 1)))


def score_confidence(probabilities: list[float]) -> float:
    """Jev's documented Score confidence: 1 - spread around the peak / spread of a uniform."""
    n = len(probabilities)
    total = sum(probabilities) or 1.0
    p = [x / total for x in probabilities]
    peak = max(range(n), key=lambda i: p[i])
    spread = sum(pi * abs(i - peak) for i, pi in enumerate(p))
    even = sum(abs(i - (n - 1) / 2) for i in range(n)) / n
    return max(0.0, min(1.0, 1 - spread / even)) if even else 1.0


def normalise(probabilities: dict[str, float]) -> tuple[dict[str, float], float]:
    """Rescale to sum to 1; also return the raw sum (a calibration diagnostic for LLMs)."""
    clean = {k: max(0.0, float(v)) for k, v in probabilities.items()}
    total = sum(clean.values())
    if total <= 0:
        return {k: 1 / len(clean) for k in clean}, total
    return {k: v / total for k, v in clean.items()}, total
