"""Prédicats : cas passants, cas refusés, évaluateurs indisponibles typés."""

import hashlib

from akasha_contracts.errors import ErrorCode
from akasha_contracts.predicates import evaluate


def _write(workdir, name, content):
    path = workdir / name
    path.write_text(content, encoding="utf-8")
    return name


def test_file_exists_passe_et_echoue(tmp_path):
    _write(tmp_path, "x.py", "print(1)\n")
    ok, err = evaluate({"predicate": "file_exists", "on": "CodeState",
                        "args": {"path": "x.py"}}, str(tmp_path))
    assert (ok, err) == (True, None)
    ok, err = evaluate({"predicate": "file_exists", "on": "CodeState",
                        "args": {"path": "absent.py"}}, str(tmp_path))
    assert not ok and err.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED


def test_file_matches_regex(tmp_path):
    _write(tmp_path, "x.py", "def compute():\n    return 1\n")
    ok, _ = evaluate({"predicate": "file_matches_regex", "on": "CodeState",
                      "args": {"path": "x.py", "pattern": "^def compute"}}, str(tmp_path))
    assert ok
    ok, err = evaluate({"predicate": "file_matches_regex", "on": "CodeState",
                        "args": {"path": "x.py", "pattern": "^def absent"}}, str(tmp_path))
    assert not ok and err.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED


def test_file_hash_equals(tmp_path):
    data = "contenu exact\n".encode("utf-8")
    (tmp_path / "n.txt").write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    ok, _ = evaluate({"predicate": "file_hash_equals", "on": "DesktopState",
                      "args": {"path": "n.txt", "sha256": digest}}, str(tmp_path))
    assert ok
    ok, err = evaluate({"predicate": "file_hash_equals", "on": "DesktopState",
                        "args": {"path": "n.txt", "sha256": "0" * 64}}, str(tmp_path))
    assert not ok


def test_chemin_hors_workspace_refuse(tmp_path):
    ok, err = evaluate({"predicate": "file_exists", "on": "CodeState",
                        "args": {"path": "../echappe.py"}}, str(tmp_path))
    assert not ok and err.code == ErrorCode.ENVIRONMENT_OBSERVATION_FAILED


def test_composition_all_of_any_of(tmp_path):
    _write(tmp_path, "x.py", "ok\n")
    ok, _ = evaluate({"all_of": [
        {"predicate": "file_exists", "on": "CodeState", "args": {"path": "x.py"}},
        {"predicate": "file_matches_regex", "on": "CodeState",
         "args": {"path": "x.py", "pattern": "ok"}}]}, str(tmp_path))
    assert ok
    ok, _ = evaluate({"any_of": [
        {"predicate": "file_exists", "on": "CodeState", "args": {"path": "non.py"}},
        {"predicate": "file_exists", "on": "CodeState", "args": {"path": "x.py"}}]},
        str(tmp_path))
    assert ok


def test_predicats_sans_evaluateur_ne_reussissent_jamais(tmp_path):
    for name in ("window_foreground", "ui_element_state"):
        ok, err = evaluate({"predicate": name, "on": "DesktopState", "args": {}},
                           str(tmp_path))
        assert (ok, err.code) == (False, ErrorCode.PREDICATE_EVALUATOR_UNAVAILABLE)
    ok, err = evaluate({"predicate": "human_confirms", "on": "HumanReview", "args": {}},
                       str(tmp_path))
    assert (ok, err.code) == (False, ErrorCode.HUMAN_CONFIRM_PENDING)
