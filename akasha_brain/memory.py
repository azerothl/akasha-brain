"""Formation et consultation de la mémoire des expériences Notes."""

import argparse
from datetime import datetime
import json
from math import isfinite
from pathlib import Path
import sqlite3
from uuid import UUID

from contracts.akasha_contracts.errors import ErrorCode, FAMILY
from contracts.akasha_contracts.validate import validate

from .experience import TECHNICAL_RESULTS
from .memory_store import MemoryRefusal, MemoryStore, encode, expiration, stamp
from .planning import ENVIRONMENT, GRAPH, RBITNET_GRAPH, RBITNET_OCR_GRAPH
from .project_common import ProjectError
from .retention import DEFAULT_POLICY, deadline, load_policy

NOTES_SCOPE = ENVIRONMENT
NOTES_GRAPHS = {"notes-baseline": GRAPH, "notes-rbitnet": RBITNET_GRAPH, "notes-rbitnet-ocr": RBITNET_OCR_GRAPH}
NOTES_ORIGINS = {"task", "synthetic_reference", "replay", "shadow", "limited"}
DESKTOP_CHECKS = ("ocr_save_button_used", "app_restarted", "ocr_note_selected_after_restart",
                  "ocr_content_visible", "sqlite_exact_row")
WORK_POLICY = {"page_size": 4, "max_items": 32, "eviction": "oldest_first", "close": "erase"}
FACTS = {"tests_passed", "sqlite_verified", "desktop_verified"}


def canonical_id(value: str) -> str:
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError("Identifiant UUID non canonique.")
    return value


def number(value) -> bool:
    return (type(value) is int and value >= 0) or (type(value) is float and isfinite(value) and value >= 0)


def extract_experience(row) -> dict | None:
    """Réduit les anciennes traces aux champs techniques admis et sans texte libre."""
    graph_id, origin = row["graph_id"], row["origin"]
    if graph_id not in NOTES_GRAPHS or origin not in NOTES_ORIGINS:
        return None
    record = json.loads(row["record"])
    if (validate(record, "ExperienceRecord") or record.get("contains_user_content") is not False
            or record["graph_version"] != "1.0.0"
            or record.get("redacted") or record["record_id"] != row["record_id"]):
        return None
    canonical_id(record["goal_id"])
    expected = NOTES_GRAPHS[graph_id]
    nodes = [{"capability_id": step[2], "version": step[3]} for step in expected]
    trace = record["verification"].get("predicate_results", [])
    route = tuple(step[0] for step in expected)
    routes = [route]
    if graph_id == "notes-rbitnet":
        routes.extend((route[:2] + route[1:], route + route[1:]))
    observed = tuple(step.get("id") for step in trace)
    if (record["node_versions"] != nodes or not any(observed == way[:len(observed)] for way in routes)
            or not number(record.get("cost", {}).get("wall_s"))):
        return None
    latest = {step["id"]: step.get("status") for step in trace}
    if (record["verification"]["status"] == "pass"
            and (observed not in routes or any(latest[step] != "passed" for step in route))):
        return None
    safe_trace = []
    for step in trace:
        if step.get("status") not in ("passed", "failed") or not number(step.get("wall_s")):
            return None
        step_id = step["id"]
        fields = step.get("result", {})
        if not isinstance(fields, dict):
            return None
        result = {key: fields[key] for key in TECHNICAL_RESULTS[step_id]
                  if type(fields.get(key)) is bool or number(fields.get(key))}
        if step_id == "verify_desktop" and isinstance(desktop := fields.get("desktop"), dict):
            result["desktop"] = {key: desktop[key] for key in DESKTOP_CHECKS if type(desktop.get(key)) is bool}
        safe_trace.append({"id": step_id, "status": step["status"], "wall_s": step["wall_s"], "result": result})
    selected = {key: record[key] for key in ("record_id", "goal_id", "graph_version", "created_at", "contains_user_content")}
    selected["node_versions"] = nodes
    selected["verification"] = {"status": record["verification"]["status"], "predicate_results": safe_trace}
    selected["cost"] = {"wall_s": record["cost"]["wall_s"]}
    errors = [{"code": code.value, "family": FAMILY[code]} for code in ErrorCode
              if any(entry["code"] == code.value for entry in record.get("errors", []))]
    if errors:
        selected["errors"] = errors
    return {"graph_id": graph_id, "origin": origin, "record": selected, "working_memory": WORK_POLICY}


def read(store, control, db, item_id, kind, now, policy):
    row = store.require(control, db, item_id, scope=NOTES_SCOPE, now=now, policy=policy)
    if row["kind"] != kind:
        raise MemoryRefusal("wrong_kind", "Le type de l'objet ne correspond pas à la demande.")
    return json.loads(row["payload"])


class NotesMemory(MemoryStore):
    def capture(self, record_ids=()) -> dict:
        """Déplace la projection dans la mémoire, dans la transaction du journal source."""
        requested = {canonical_id(item_id) for item_id in record_ids}
        policy = load_policy()
        counts = {"captured": 0, "excluded": 0, "expired": 0}
        with self.access() as (control, db):
            if not self.enabled(control):
                return {"status": "disabled", **counts}
            columns = {column[1] for column in db.execute("PRAGMA table_info(experiences)")}
            if not columns:
                return counts
            expiry_column = "expires_at" if "expires_at" in columns else "NULL AS expires_at"
            now = self.clock()
            for row in db.execute(f"SELECT record_id, graph_id, origin, record, {expiry_column} FROM experiences"):
                item_id = row["record_id"]
                if requested and item_id not in requested:
                    continue
                try:
                    selected = extract_experience(row)
                    if selected is None:
                        counts["excluded"] += 1
                        continue
                    canonical_id(item_id)
                    created = datetime.fromisoformat(selected["record"]["created_at"])
                    old_limit = (datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else
                                 deadline(created, "minimized_results", policy=DEFAULT_POLICY))
                except (KeyError, TypeError, ValueError):
                    counts["excluded"] += 1
                    continue
                try:
                    self.save(control, db, kind="experience", scope=NOTES_SCOPE, payload=selected, now=now,
                              policy=policy, item_id=item_id, created_at=created, prior_deadline=old_limit)
                except MemoryRefusal as error:
                    if error.code != "retention_expired":
                        raise
                    counts["expired"] += 1
                    continue
                db.execute("DELETE FROM experiences WHERE record_id = ?", (item_id,))
                counts["captured"] += 1
        return counts

    def experience(self, item_id: str) -> dict:
        with self.access() as (control, db):
            self.require_enabled(control)
            return read(self, control, db, canonical_id(item_id), "experience", self.clock(), load_policy())

    def open_window(self, anchor: str, entries: list[str]) -> str:
        anchor = canonical_id(anchor)
        policy = load_policy()
        with self.access() as (control, db):
            self.require_enabled(control)
            now = self.clock()
            experience = read(self, control, db, anchor, "experience", now, policy)
            work = experience["working_memory"]
            kept = list(dict.fromkeys(reversed([canonical_id(item) for item in entries])))[:work["max_items"]]
            kept.reverse()
            return self.save(control, db, kind="work_window", scope=NOTES_SCOPE, now=now, policy=policy,
                             payload={"entries": kept, "page_size": work["page_size"]}, parents=(anchor, *kept))

    def page(self, window: str, cursor: int = 0) -> dict:
        if cursor < 0:
            raise ValueError("Le curseur doit être positif.")
        policy = load_policy()
        with self.access() as (control, db):
            self.require_enabled(control)
            now = self.clock()
            content = read(self, control, db, canonical_id(window), "work_window", now, policy)
            entries = content["entries"]
            end = cursor + content["page_size"]
            page = [read(self, control, db, item, "experience", now, policy) for item in entries[cursor:end]]
            return {"items": page, "next_cursor": end if end < len(entries) else None}

    def close_window(self, window: str) -> dict:
        window = canonical_id(window)
        with self.access() as (control, db):
            read(self, control, db, window, "work_window", self.clock(), load_policy())
        self.request_erasure(window)
        return self.finish_erasures()

    def record_fact(self, item_id: str, name: str, valid_from: datetime, valid_to: datetime | None = None) -> str:
        if name not in FACTS or (valid_to is not None and stamp(valid_from) >= stamp(valid_to)):
            raise ValueError("Fait ou intervalle de validité invalide.")
        item_id = canonical_id(item_id)
        policy = load_policy()
        with self.access() as (control, db):
            self.require_enabled(control)
            now = self.clock()
            experience = read(self, control, db, item_id, "experience", now, policy)
            checks = {step["id"]: step["result"] for step in experience["record"]["verification"]["predicate_results"]}
            verification = checks.get("verify", {})
            desktop = checks.get("verify_desktop", {}).get("desktop", {})
            facts = {"tests_passed": verification.get("passed"),
                     "sqlite_verified": None, "desktop_verified": None}
            if "sqlite_verifier_exit" in verification:
                facts["sqlite_verified"] = verification["sqlite_verifier_exit"] == 0
            if all(key in desktop for key in DESKTOP_CHECKS):
                facts["desktop_verified"] = all(desktop[key] for key in DESKTOP_CHECKS)
            if facts[name] is None:
                raise MemoryRefusal("missing_evidence", "L'expérience ne contient pas l'observation demandée.")
            return self.save(control, db, kind="fact", scope=NOTES_SCOPE, now=now, policy=policy, parents=(item_id,),
                             payload={"graph": experience["graph_id"], "name": name, "value": facts[name],
                                      "valid_from": stamp(valid_from), "valid_to": stamp(valid_to) if valid_to else None})

    def fact_at(self, graph: str, name: str, valid_at: datetime, *, recorded_as_of: datetime | None = None) -> dict | None:
        if graph not in NOTES_GRAPHS or name not in FACTS:
            raise ValueError("Graphe ou fait inconnu.")
        valid = stamp(valid_at)
        policy = load_policy()
        with self.access() as (control, db):
            self.require_enabled(control)
            now = self.clock()
            rows = db.execute("""SELECT id, created_at, payload FROM memory_items
                WHERE scope = ? AND kind = 'fact' AND created_at <= ?
                AND json_extract(payload, '$.graph') = ? AND json_extract(payload, '$.name') = ?
                AND json_extract(payload, '$.valid_from') <= ?
                AND (json_extract(payload, '$.valid_to') IS NULL OR json_extract(payload, '$.valid_to') > ?)
                ORDER BY created_at DESC, rowid DESC""", (NOTES_SCOPE, stamp(recorded_as_of or now), graph, name, valid, valid))
            for item in rows:
                try:
                    self.require(control, db, item["id"], scope=NOTES_SCOPE, now=now, policy=policy)
                except MemoryRefusal as error:
                    if error.code not in ("erasure_requested", "retention_expired"):
                        raise
                    continue
                return {"id": item["id"], "recorded_at": item["created_at"], **json.loads(item["payload"])}
        return None

    def inventory(self) -> list[dict]:
        policy = load_policy()
        with self.access() as (control, db):
            now = self.clock()
            result = []
            for item in db.execute("SELECT * FROM memory_items WHERE scope = ? ORDER BY created_at, id", (NOTES_SCOPE,)):
                try:
                    self.require(control, db, item["id"], scope=NOTES_SCOPE, now=now, policy=policy)
                except MemoryRefusal as error:
                    if error.code not in ("erasure_requested", "retention_expired", "redacted_by_deletion"):
                        raise
                    continue
                result.append({"id": item["id"], "kind": item["kind"], "expires_at": stamp(expiration(item, policy))})
            return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Mémoire effaçable du banc local Notes.")
    parser.add_argument("--db", type=Path, required=True, help="Journal SQLite Notes")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    command = commands.add_parser("capture")
    command.add_argument("records", nargs="*")
    commands.add_parser("list")
    command = commands.add_parser("read")
    command.add_argument("id")
    command = commands.add_parser("open-window")
    command.add_argument("anchor")
    command.add_argument("entries", nargs="+")
    command = commands.add_parser("page")
    command.add_argument("id")
    command.add_argument("--cursor", type=int, default=0)
    command = commands.add_parser("close-window")
    command.add_argument("id")
    command = commands.add_parser("extract-fact")
    command.add_argument("id")
    command.add_argument("name", choices=sorted(FACTS))
    command.add_argument("valid_from", type=datetime.fromisoformat)
    command.add_argument("--valid-to", type=datetime.fromisoformat)
    command = commands.add_parser("fact-at")
    command.add_argument("graph", choices=sorted(NOTES_GRAPHS))
    command.add_argument("name", choices=sorted(FACTS))
    command.add_argument("valid_at", type=datetime.fromisoformat)
    command.add_argument("--recorded-as-of", type=datetime.fromisoformat)
    command = commands.add_parser("erase")
    command.add_argument("id")
    command = commands.add_parser("request-erasure")
    command.add_argument("id")
    commands.add_parser("finish-erasures")
    commands.add_parser("sweep")
    args = parser.parse_args()
    memory = NotesMemory(args.db)
    try:
        if args.command == "init":
            memory.initialize()
            result = {"status": "ready"}
        elif args.command == "capture":
            result = memory.capture(args.records)
        elif args.command == "list":
            result = memory.inventory()
        elif args.command == "read":
            result = memory.experience(args.id)
        elif args.command == "open-window":
            result = {"window": memory.open_window(args.anchor, args.entries)}
        elif args.command == "page":
            result = memory.page(args.id, args.cursor)
        elif args.command == "close-window":
            result = memory.close_window(args.id)
        elif args.command == "extract-fact":
            result = {"id": memory.record_fact(args.id, args.name, args.valid_from, args.valid_to)}
        elif args.command == "fact-at":
            result = memory.fact_at(args.graph, args.name, args.valid_at, recorded_as_of=args.recorded_as_of)
        elif args.command == "erase":
            memory.request_erasure(canonical_id(args.id))
            result = memory.finish_erasures()
        elif args.command == "request-erasure":
            memory.request_erasure(canonical_id(args.id))
            result = {"status": "requested"}
        elif args.command == "finish-erasures":
            result = memory.finish_erasures()
        else:
            from .memory_budget import enforce

            result = memory.expire()
            if budget := enforce(memory):
                result["disk"] = budget
    except (MemoryRefusal, ValueError) as error:
        print(encode({"status": "refused", "code": getattr(error, "code", "invalid_input"), "message": str(error)}))
        return 1
    except (ProjectError, sqlite3.Error, OSError):
        if args.command in {"erase", "request-erasure", "finish-erasures", "sweep", "close-window"}:
            result = {"status": "pending", "code": "storage_unverified"}
        else:
            result = {"status": "refused", "code": "storage_unverified"}
        print(encode(result))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
