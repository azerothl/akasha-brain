"""Compare le choix issu des simulations G4 sur les stockages SQLite du banc Notes."""

import json
import os
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from contextlib import closing
from itertools import product
from multiprocessing import get_context
from pathlib import Path
from tempfile import TemporaryDirectory

from akasha_brain.idle_simulation import PLANS, replay_case, snapshot, synthetic_cases
from bench.notes.notes_store import NoteStore as FaultyStore
from bench.reference.notes_reference_store import NoteStore as ReferenceStore
from bench.run_phase5_notes_action_selection import select_plan


NOTE = ("Carnet", "À reprendre demain")


def open_store(db, faulty, save):
    with closing((FaultyStore if faulty else ReferenceStore)(db)) as store:
        if save:
            store.save_note(*NOTE)
        return os.getpid()


def rows(db):
    with closing(sqlite3.connect(db)) as reader:
        return reader.execute("SELECT title, content FROM notes ORDER BY id").fetchall()


def execute(db, faulty, saved, goal, predictor):
    # Préparer chaque bras séparément, y compris la note antérieure à la panne.
    with closing(ReferenceStore(db)) as setup:
        if saved:
            setup.save_note(*NOTE)
    before = rows(db)
    if before != ([NOTE] if saved else []):
        raise RuntimeError("État initial différent du cas prévu.")
    context = get_context("spawn")
    with ProcessPoolExecutor(1, mp_context=context) as first:
        pid = first.submit(os.getpid).result()
        decision = select_plan(PLANS, goal, snapshot(pid, NOTE in before), use_predictor=predictor)
        steps = decision["steps"]
        if first.submit(open_store, db, faulty, "save" in steps).result() != pid:
            raise RuntimeError("Le processus Notes a changé avant la fermeture.")
    final_pid = pid
    if "restart" in steps:
        with ProcessPoolExecutor(1, mp_context=context) as second:
            final_pid = second.submit(open_store, db, faulty, False).result()
    relation = "same" if final_pid == pid else "different"
    expected = [NOTE] if goal["exact_fixture_present"] else []
    persisted = rows(db)
    return {"plan": steps, "rows": len(persisted), "pid_relation": relation,
            "passed": persisted == expected and goal["pid_relation"] in ("any", relation)}


def evaluate(root):
    # Geler le choix avant de consulter les résultats SQLite.
    dreams = [replay_case(case)["trials"] for case in synthetic_cases(23, 8)]
    scores = {arm: sum(trial[arm]["passed"] for trial in dreams) for arm in ("reference", "candidate")}
    selected = "candidate" if scores["candidate"] > scores["reference"] else "reference"
    cases = []
    for faulty, (saved, wanted), relation in product(
        (False, True), ((False, True), (True, True), (False, False)), ("any", "same", "different")
    ):
        goal = {"exact_fixture_present": wanted, "pid_relation": relation}
        arms = {arm: execute(root / f"{len(cases)}-{arm}.db", faulty, saved, goal, arm == "candidate")
                for arm in scores}
        cases.append({"faulty": faulty, "saved": saved, "goal": goal, "arms": arms})
    verified = {arm: sum(case["arms"][arm]["passed"] for case in cases) for arm in scores}
    return {"scope": "notes_sqlite_store", "synthetic_scores": scores, "selected": selected,
            "verified": verified, "cases": cases}


if __name__ == "__main__":
    with TemporaryDirectory(prefix="akasha-notes-eval-") as directory:
        print(json.dumps(evaluate(Path(directory)), indent=2))
