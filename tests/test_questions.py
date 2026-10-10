import pytest
import yaml

from classmark.backends.claude import answer_schema
from classmark.backends.jev import to_typesafe
from classmark.questions import load_question_set


def write(tmp_path, data):
    path = tmp_path / "q.yaml"
    path.write_text(yaml.safe_dump(data))
    return path


def test_shipped_question_sets_are_valid():
    e1 = load_question_set("e1")
    assert len(e1.questions["resource_type"].options) == 32
    e2 = load_question_set("e2").all_questions()
    assert len(e2["fos"].options) == 6
    assert sum(len(q.options) for qid, q in e2.items() if qid != "fos") == 42


def test_choice_needs_two_options(tmp_path):
    path = write(tmp_path, {"experiment": "x", "title": "x", "label": "x",
                            "questions": {"q": {"type": "choice", "instructions": "?", "options": {"a": None}}}})
    with pytest.raises(ValueError, match="at least two options"):
        load_question_set(path)


def test_options_on_noul_rejected(tmp_path):
    path = write(tmp_path, {"experiment": "x", "title": "x", "label": "x",
                            "questions": {"q": {"type": "noul", "instructions": "?", "options": {"a": None}}}})
    with pytest.raises(ValueError, match="only allowed on choice"):
        load_question_set(path)


def test_bad_yaml_gives_steward_friendly_error(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text("questions:\n  q:\n    instructions: Chemistry: organic\n")
    with pytest.raises(ValueError, match="colon followed by a space"):
        load_question_set(path)


def test_reverse_options():
    q = load_question_set("e2").all_questions(reverse_options=True)["fos"]
    assert list(q.options)[0] == "Humanities"


def test_backend_payloads_cover_every_question():
    questions = load_question_set("e2").all_questions()
    schema = answer_schema(questions)
    assert set(schema["required"]) == set(questions)
    assert to_typesafe(questions["fos"])["criteria"] == questions["fos"].options
