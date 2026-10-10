"""Load and validate question sets written in YAML.

A question set is a YAML file in ``questions/`` that data stewards can edit
without touching Python. See the README for the format. Validation errors name
the file and the field at fault, so a typo is reported clearly rather than
surfacing later as a failed API call.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, model_validator

from classmark import config

MAX_CHOICE_OPTIONS = 255  # Jev's documented limit


class Question(BaseModel):
    """One typed question. The id is the key it is stored under, not sent to the model."""

    type: Literal["choice", "score", "noul"]
    instructions: str
    # Choice: option name -> description (or null when the name is self-explanatory).
    options: dict[str, str | None] | None = None
    # Score: ordered level descriptions, lowest first.
    levels: list[str] | None = None

    @model_validator(mode="after")
    def _check_shape(self) -> "Question":
        if self.type == "choice":
            if not self.options or len(self.options) < 2:
                raise ValueError("a choice question needs at least two options")
            if len(self.options) > MAX_CHOICE_OPTIONS:
                raise ValueError(f"a choice question allows at most {MAX_CHOICE_OPTIONS} options")
        elif self.options:
            raise ValueError(f"'options' is only allowed on choice questions, not {self.type}")
        if self.type == "score":
            if not self.levels or len(self.levels) < 2:
                raise ValueError("a score question needs at least two levels")
        elif self.levels:
            raise ValueError(f"'levels' is only allowed on score questions, not {self.type}")
        return self

    def reversed_options(self) -> "Question":
        """The same question with choice options in reverse order (position-bias check)."""
        if self.type != "choice":
            return self
        return self.model_copy(update={"options": dict(reversed(list(self.options.items())))})


class Node(BaseModel):
    description: str | None = None
    children: dict[str, "Node | str | None"] | None = None


class Hierarchy(BaseModel):
    """A two-or-more-level taxonomy asked as chained Choice questions.

    Every level is asked in the same request (speculative fan-out): one question
    for the top level, plus one per parent node that asks which child applies
    *assuming* that parent. Beam search over the probabilities then runs in code.
    """

    id: str
    instructions: str
    child_instructions: str = Field(
        description="Template for child questions; '{parent}' is replaced by the parent's name."
    )
    options: dict[str, Node]


class QuestionSet(BaseModel):
    experiment: str
    title: str
    label: str = Field(description="Key in each record's 'labels' that holds the gold answer.")
    exclude_from_state: list[str] = Field(default_factory=list)
    questions: dict[str, Question] = Field(default_factory=dict)
    hierarchy: Hierarchy | None = None

    @model_validator(mode="after")
    def _check_has_questions(self) -> "QuestionSet":
        if not self.questions and not self.hierarchy:
            raise ValueError("a question set needs 'questions', 'hierarchy', or both")
        return self

    def all_questions(self, reverse_options: bool = False) -> dict[str, Question]:
        """Every question to send in one request, including expanded hierarchy levels."""
        questions = dict(self.questions)
        if self.hierarchy:
            questions.update(expand_hierarchy(self.hierarchy))
        if reverse_options:
            questions = {qid: q.reversed_options() for qid, q in questions.items()}
        return questions


HIERARCHY_SEPARATOR = " > "


def expand_hierarchy(h: Hierarchy) -> dict[str, Question]:
    """Turn a taxonomy into one top-level question and one question per parent node.

    Question ids are paths such as ``fos`` and ``fos > Natural sciences``.
    """
    questions: dict[str, Question] = {}

    def add(qid: str, instructions: str, nodes: dict[str, Node]) -> None:
        questions[qid] = Question(
            type="choice",
            instructions=instructions,
            options={name: node.description for name, node in nodes.items()},
        )
        for name, node in nodes.items():
            if node.children:
                children = {
                    child: c if isinstance(c, Node) else Node(description=c) for child, c in node.children.items()
                }
                add(
                    qid + HIERARCHY_SEPARATOR + name,
                    h.child_instructions.replace("{parent}", name),
                    children,
                )

    add(h.id, h.instructions, h.options)
    return questions


def load_question_set(name_or_path: str | Path) -> QuestionSet:
    """Load ``questions/<name>.yaml`` (or an explicit path) and validate it."""
    path = Path(name_or_path)
    if not path.suffix:
        matches = sorted(config.QUESTIONS_DIR.glob(f"{name_or_path}*.yaml"))
        if len(matches) != 1:
            found = ", ".join(m.stem for m in matches) or "none"
            raise FileNotFoundError(
                f"expected exactly one question set matching '{name_or_path}' in {config.QUESTIONS_DIR}; found {found}"
            )
        path = matches[0]
    with path.open(encoding="utf-8") as f:
        try:
            raw = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ValueError(
                f"{path} is not valid YAML. A common cause is a colon followed by a "
                f"space inside an unquoted description; put the description in "
                f"quotes or use '>' on the line before it.\n{e}"
            ) from e
    try:
        return QuestionSet.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"invalid question set {path}:\n{e}") from e
