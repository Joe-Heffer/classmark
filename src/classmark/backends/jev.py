"""TypeSafe Jev backend: all questions for a record in one System One request."""

import time

from classmark import config
from classmark.backends.base import Backend, Response
from classmark.questions import Question


def to_typesafe(q: Question) -> dict:
    """A question in the TypeSafe API's raw dictionary form."""
    if q.type == "choice":
        return {"type": "choice", "instructions": q.instructions, "criteria": q.options}
    if q.type == "score":
        return {"type": "score", "instructions": q.instructions, "criteria": q.levels}
    return {"type": "noul", "instructions": q.instructions}


class JevBackend(Backend):
    name = "jev"

    def __init__(self, model: str = config.JEV_MODEL):
        self.model = model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from typesafe_sdk import TypeSafeClient  # reads TYPESAFE_API_KEY

            self._client = TypeSafeClient(model=self.model)
        return self._client

    def build_request(self, state: dict, questions: dict[str, Question]) -> dict:
        return {
            "model": self.model,
            "state": state,
            "questions": {qid: to_typesafe(q) for qid, q in questions.items()},
        }

    def estimate_tokens(self, payload: dict) -> tuple[int, int]:
        # About 3 characters per token for JSON-heavy text; deliberately pessimistic.
        from classmark.store import canonical

        return len(canonical(payload)) // 3 + 1, 0

    def call(self, payload: dict, questions: dict[str, Question]) -> Response:
        start = time.perf_counter()
        result = self.client.system_one(state=payload["state"], questions=payload["questions"], model=payload["model"])
        latency = time.perf_counter() - start
        raw = result.raw_http_response.json()
        answers = {}
        for qid, a in raw["answers"].items():
            if a["type"] == "choice":
                answers[qid] = {
                    "type": "choice",
                    "choice": a["choice"],
                    "probabilities": a["probabilities"],
                    "confidence": a["confidence"],
                }
            elif a["type"] == "score":
                answers[qid] = {
                    "type": "score",
                    "score": a["score"],
                    "probabilities": a["probabilities"],
                    "confidence": a["confidence"],
                }
            else:
                answers[qid] = {"type": "noul", "noul": a["noul"]}
        usage = raw.get("usage") or {}
        return Response(
            answers=answers,
            model=raw.get("model", self.model),
            input_tokens=usage.get("input_tokens") or 0,
            output_tokens=usage.get("output_tokens") or 0,
            latency_s=latency,
            request_id=result.request_id,
            raw=raw,
        )
