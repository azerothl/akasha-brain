"""Compare le filtre de préconditions et mesure le rejeu Notes en bac neuf."""

from argparse import ArgumentParser
from contextlib import closing
from dataclasses import replace
import json
from pathlib import Path
import sqlite3
from statistics import median
from time import perf_counter

from akasha_brain.memory import NotesMemory
from akasha_brain.memory_store import MemoryRefusal
from akasha_brain.memory_workflows import WorkflowLibrary, measured_outcome, observe
from akasha_brain.notes_evolution import CANDIDATE, GOAL_FILE, PARENT
from akasha_brain.notes_repair import RbitnetPaths
from akasha_brain.notes_runtime import run_notes
from akasha_brain.planning import load_catalog
from bench.run_guided_repair import execution_limits, write_report


def ranking_trial(library, goal, catalog, runtime):
    code_text = "notes sauvegarde correction persistance sqlite note code tests"
    desktop_text = "notes sauvegarde correction persistance sqlite note relance bureau redémarrage ocr"
    code = {**goal, "user_intent": code_text}
    visual = {**goal, "user_intent": desktop_text}
    context = observe(runtime, True)
    assert context.ocr_available and context.isolated_runtime_available
    code_context = replace(context, desktop_requested=False)
    cases = (
        ("notes_ocr_nominal", visual, catalog, context, CANDIDATE),
        ("notes_code_nominal", code, catalog, code_context, PARENT),
        ("notes_ocr_termes_code", code, catalog, context, CANDIDATE),
        ("notes_code_termes_ocr", visual, catalog, code_context, PARENT),
        ("ecriture_hors_perimetre", {**visual, "constraints": {**goal["constraints"],
         "allowed_actions": ["observe", "test"]}}, catalog, context, None),
        ("approbation_en_attente", {**visual, "approval_requirements": ["confirmer"]}, catalog, context, None),
        ("cible_ambigue", {**code, "uncertainties": ["instance"]}, catalog, code_context, None),
        ("transfert_reserve", {**code, "inputs": ["bench://tasks"],
         "constraints": {**goal["constraints"], "environment_id": "bench-tasks"}}, catalog, code_context, None),
        ("ocr_absent", visual, catalog, replace(context, ocr_available=False), None),
        ("code_sans_ocr", code, catalog, replace(code_context, ocr_available=False), PARENT),
        ("bac_indisponible", visual, catalog, replace(context, isolated_runtime_available=False), None),
        ("version_capacite_absente", code, {key: entry for key, entry in catalog.items()
         if key[0] != "notes.repair_rbitnet"}, code_context, None),
        ("verificateur_modifie", visual, catalog, replace(context, files={**context.files,
         "text": {**context.files["text"], "verifiers/verify_notes.py": "changed"}}), None),
    )
    results = []
    for case, request, capabilities, state, expected in cases:
        comparison = library.compare(request, capabilities, state)
        choices = {arm: comparison[arm]["graph"] if comparison[arm] else None
                   for arm in ("similarity", "filtered_similarity", "gated")}
        results.append({"case": case, "expected": expected, **choices,
                        "refusals": {entry["graph"]: entry["refusals"] for entry in comparison["candidates"]}})
    counts = {arm: {"correct": sum(row[arm] == row["expected"] for row in results),
                    "unsafe_selections": sum(row[arm] is not None and row[arm] != row["expected"] for row in results)}
              for arm in ("similarity", "filtered_similarity", "gated")}
    return {"counts": counts, "cases": results}


def measure(args) -> dict:
    source = args.phase1.resolve(strict=True)
    output = args.output.resolve()
    runtime = args.runtime.resolve(strict=True)
    output.mkdir(parents=True)
    memory = NotesMemory(output / "journal.sqlite")
    journal = (source / "registry.db").as_uri() + "?mode=ro"
    with closing(sqlite3.connect(journal, uri=True)) as old, closing(sqlite3.connect(memory.path)) as local:
        old.backup(local)
    memory.initialize()
    assert memory.capture() == {"captured": 6, "excluded": 0, "expired": 0}
    library = WorkflowLibrary(memory)
    library.install()
    parent = library.publish([source / item / "report.json" for item in ("cycle", "rollback-proof")])
    desktop_reports = [source / "cycle" / "evolution" / stage / "report.json" for stage in ("replay", "shadow", "limited")]
    desktop = library.publish(desktop_reports)
    evidence = {"status": "running", "library": {PARENT: parent["proofs"], CANDIDATE: desktop["proofs"]}}
    goal = json.loads(GOAL_FILE.read_bytes())
    catalog = load_catalog()
    evidence["ranking"] = ranking_trial(library, goal, catalog, runtime)
    write_report(output, evidence)
    print("A/B", json.dumps(evidence["ranking"]["counts"]), flush=True)
    assert evidence["ranking"]["counts"]["gated"] == {"correct": 13, "unsafe_selections": 0}
    if args.ranking_only:
        evidence["status"] = "passed"
        write_report(output, evidence)
        return {"status": "passed", "counts": evidence["ranking"]["counts"]}

    traces = []
    trials = evidence["trials"] = []
    observed = None
    repair = RbitnetPaths(*args.rbitnet, model_ram_mib=8192)
    for number, arms in enumerate((("generation", "reuse"), ("reuse", "generation")), start=1):
        for arm in arms:
            began = perf_counter()
            if arm == "generation":
                with execution_limits(None, cpu_threads=8, model_ram_mb=8192):
                    report = run_notes(goal, catalog, runtime, output / f"generation-{number}", repair,
                                       first_diff_seed=742 + number - 1, rapidocr=True)
                result = {"status": report["status"], "outcome": measured_outcome(report), "sandbox_wall_s": report["wall_s"]}
            else:
                result = library.run(goal, runtime, desktop=True, trace_id=traces[0] if traces else None)
                if result["status"] == "passed":
                    traces.append(result["trace"])
            wall = round(perf_counter() - began, 3)
            trials.append({"pair": number, "arm": arm, **result, "wall_s": wall})
            write_report(output, evidence)
            print(number, arm, result["status"], wall, flush=True)
            assert result["status"] == "passed", result
            if observed is None:
                observed = result["outcome"]
            assert observed == result["outcome"], (observed, result["outcome"])
    metrics = {arm: median(row["wall_s"] for row in trials if row["arm"] == arm)
               for arm in ("generation", "reuse")}
    evidence["median_wall_s"] = {key: round(value, 3) for key, value in metrics.items()}
    evidence["saved_s"] = round(metrics["generation"] - metrics["reuse"], 3)
    evidence["replayed_identically"] = True

    deleted = json.loads(desktop_reports[0].read_bytes())["experience_record_id"]
    memory.request_erasure(deleted)
    for trace in traces:
        try:
            library.run(goal, runtime, desktop=True, trace_id=trace)
        except MemoryRefusal as error:
            assert error.code == "redacted_by_deletion"
        else:
            raise AssertionError("Une trace expurgée est encore rejouable.")
    evidence["erasure"] = memory.finish_erasures()
    assert evidence["erasure"]["removed"] == 7
    assert library.compare(goal, catalog, observe(runtime, True))["gated"] is None
    assert not list(library.scratch.iterdir())
    evidence["erasure"]["traces_refused"] = len(traces)
    evidence["rollback"] = library.rollback()
    assert evidence["rollback"]["default_graph"] == PARENT and not evidence["rollback"]["memory_enabled"]
    assert memory.capture()["status"] == "disabled"
    assert library.compare(goal, catalog, observe(runtime, False))["gated"] is None
    evidence["status"] = "passed"
    write_report(output, evidence)
    return {key: value for key, value in evidence.items() if key not in {"ranking", "trials"}}


def main() -> None:
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--phase1", type=Path, required=True, help="Dossier de preuves du cycle Notes CPU")
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--rbitnet", nargs=3, type=Path, metavar=("BINAIRE", "GGUF", "TOKENIZER"))
    parser.add_argument("--ranking-only", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.ranking_only and args.rbitnet is None:
        parser.error("--rbitnet est requis pour les essais en bac")
    print(json.dumps(measure(args), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
