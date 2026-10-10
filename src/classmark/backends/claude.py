"""Claude baseline: the same questions, answered through the Messages API with structured output.

Claude is asked for a label and a probability for every option. These are
self-reported probabilities, not model likelihoods: they are rescaled to sum to
1, and the raw sum is kept as a diagnostic. Confidence is then computed with
Jev's published formulae so that the two systems are compared like for like.
The prediction used for evaluation is the most probable option, for both
systems; whether Claude's stated label agrees with it is recorded too.
"""

import json
import time

from classmark import config
from classmark.backends.base import (
    Backend,
    Response,
    choice_confidence,
    normalise,
    score_confidence,
)
from classmark.questions import Question

SYSTEM_PROMPT = """\
You classify research data repository records. You receive a JSON "state" \
describing one record (title, description and a deterministic profile of its \
files) and a set of questions about it.

Answer every question independently, using only the state. Each question \
stands alone: do not let your answer to one question change another.

* For a choice question, give the single best option as "choice" and a \
probability for every option in "probabilities". The probabilities should sum \
to 1 and should reflect how likely each option is to be correct, so that \
across many records an option you give 0.8 is right about 80% of the time.
* For a score question, give a probability for every level, lowest level first.
* For a yes/no question, give the probability that the answer is yes.

Some questions begin "Assume ...". Answer them as if the assumption were true, \
even if you think it is not."""


def describe_questions(questions: dict[str, Question]) -> list[dict]:
    out = []
    for qid, q in questions.items():
        item = {"id": qid, "type": {"noul": "yes/no"}.get(q.type, q.type), "instructions": q.instructions}
        if q.type == "choice":
            item["options"] = q.options
        if q.type == "score":
            item["levels"] = {str(i): d for i, d in enumerate(q.levels)}
        out.append(item)
    return out


def number_map(keys: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": "number"} for k in keys},
        "required": list(keys),
        "additionalProperties": False,
    }


def answer_schema(questions: dict[str, Question]) -> dict:
    props = {}
    for qid, q in questions.items():
        if q.type == "choice":
            opts = list(q.options)
            props[qid] = {
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "enum": opts},
                    "probabilities": number_map(opts),
                },
                "required": ["choice", "probabilities"],
                "additionalProperties": False,
            }
        elif q.type == "score":
            props[qid] = {
                "type": "object",
                "properties": {"probabilities": number_map([str(i) for i in range(len(q.levels))])},
                "required": ["probabilities"],
                "additionalProperties": False,
            }
        else:
            props[qid] = {
                "type": "object",
                "properties": {"probability_yes": {"type": "number"}},
                "required": ["probability_yes"],
                "additionalProperties": False,
            }
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


class ClaudeBackend(Backend):
    name = "claude"

    def __init__(self, model: str = config.CLAUDE_MODEL, effort: str = config.CLAUDE_EFFORT):
        self.model = model
        self.effort = effort
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic  # reads ANTHROPIC_API_KEY

            self._client = anthropic.Anthropic()
        return self._client

    def settings(self) -> dict:
        return {"effort": self.effort, "max_tokens": config.CLAUDE_MAX_TOKENS}

    def build_request(self, state: dict, questions: dict[str, Question]) -> dict:
        user = (
            "<state>\n" + json.dumps(state, ensure_ascii=False, indent=1) + "\n</state>\n\n"
            "<questions>\n" + json.dumps(describe_questions(questions), ensure_ascii=False, indent=1) + "\n</questions>"
        )
        return {
            "model": self.model,
            "max_tokens": config.CLAUDE_MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": user}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": answer_schema(questions)},
            },
        }

    def estimate_tokens(self, payload: dict) -> tuple[int, int]:
        text = payload["system"] + payload["messages"][0]["content"]
        schema = json.dumps(payload["output_config"]["format"]["schema"])
        return (len(text) + len(schema)) // 3 + 1, payload["max_tokens"]

    def call(self, payload: dict, questions: dict[str, Question]) -> Response:
        start = time.perf_counter()
        message = self.client.messages.create(**payload)
        latency = time.perf_counter() - start
        raw = message.to_dict()
        common = dict(
            model=message.model,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            latency_s=latency,
            request_id=message._request_id,
            raw=raw,
        )
        if message.stop_reason != "end_turn":
            # Tokens were still spent, so return the usage with no answers.
            return Response(answers={}, diagnostics={"error": f"stop_reason={message.stop_reason}"}, **common)
        text = next(b.text for b in message.content if b.type == "text")
        parsed = json.loads(text)

        answers, diagnostics = {}, {}
        for qid, q in questions.items():
            a = parsed[qid]
            if q.type == "choice":
                probs, raw_sum = normalise(a["probabilities"])
                argmax = max(probs, key=probs.get)
                answers[qid] = {
                    "type": "choice",
                    "choice": argmax,
                    "probabilities": probs,
                    "confidence": choice_confidence(probs),
                }
                diagnostics[qid] = {
                    "stated_choice": a["choice"],
                    "stated_matches_argmax": a["choice"] == argmax,
                    "raw_probability_sum": raw_sum,
                }
            elif q.type == "score":
                probs, raw_sum = normalise(a["probabilities"])
                values = [probs[str(i)] for i in range(len(q.levels))]
                answers[qid] = {
                    "type": "score",
                    "score": sum(i * p for i, p in enumerate(values)),
                    "probabilities": probs,
                    "confidence": score_confidence(values),
                }
                diagnostics[qid] = {"raw_probability_sum": raw_sum}
            else:
                answers[qid] = {"type": "noul", "noul": min(1.0, max(0.0, float(a["probability_yes"])))}

        return Response(answers=answers, diagnostics=diagnostics, **common)
