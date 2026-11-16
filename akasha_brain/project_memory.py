"""Références et traces effaçables du parcours projet soumis à consentement."""

from datetime import datetime
import json

from .evolution_consent import ReuseScope, check_reuse
from .memory_store import MemoryRefusal, MemoryStore, row_for
from .project_common import project_scope
from .project_evolution import erasure_marker, registry_path, require_sample
from .retention import load_policy


def require_reference(db, row, now, *, trace: bool) -> None:
    data = json.loads(row["payload"])
    scope = row["scope"]
    if erasure_marker(db, scope, sample_id=row["id"], source_id=data["source_id"]):
        if trace:
            raise MemoryRefusal("redacted_by_deletion", "Trace expurgée. Rejeu indisponible.")
        raise MemoryRefusal("erasure_requested", "Copie bloquée par une demande d'effacement.")
    consent = ReuseScope(scope, data["category"], data["consent_id"], "project", False)
    if denied := check_reuse(db, (consent,), now=now):
        raise MemoryRefusal(denied.details.get("reason", "permission_denied"), denied.message)


class ProjectMemory(MemoryStore):
    def __init__(self, project, registry):
        self.project = project.resolve(strict=True)
        self.scope = project_scope(self.project)
        super().__init__(registry_path(self.project, registry))

    def reference(self, control, db, sample, now, policy) -> str:
        if sample.scope.project != self.scope:
            raise MemoryRefusal("out_of_scope", "Copie d'un autre projet.")
        require_sample(db, sample)
        item = row_for(db, sample.sample_id)
        if item is None:
            self.save(control, db, kind="project_reference", scope=self.scope, now=now, policy=policy,
                      payload={"category": sample.scope.category, "consent_id": sample.scope.consent_id,
                               "source_id": sample.manifest["source_id"]},
                      item_id=sample.sample_id, created_at=datetime.fromisoformat(sample.created_at),
                      prior_deadline=datetime.fromisoformat(sample.expires_at), retention="real_contents")
        else:
            self.require(control, db, sample.sample_id, scope=self.scope, now=now, policy=policy)
        return sample.sample_id

    def check_project(self) -> None:
        if project_scope(self.project) != self.scope:
            raise MemoryRefusal("out_of_scope", "L'identité du projet a changé.")

    def capture(self, sample, *, validation=None) -> dict:
        self.check_project()
        policy = load_policy()
        with self.access() as (control, db):
            if not self.enabled(control):
                return {"status": "disabled"}
            now = self.clock()
            reference = self.reference(control, db, sample, now, policy)
            result = {"status": "referenced", "id": reference}
            if validation is not None:
                result["trace"] = self.save(
                    control, db, kind="trace", scope=self.scope, now=now, policy=policy, parents=(reference,),
                    retention="real_contents",
                    payload={"status": "passed" if validation.get("status") == "passed" else "failed",
                             "verified_guest": validation.get("guest_exit_code") == 0x4700,
                             "read_only_input": validation.get("read_only_input") is True,
                             "sandbox_stopped": validation.get("sandbox_stopped") is True})
            return result

    def recall(self, item_id: str) -> dict:
        self.check_project()
        with self.access() as (control, db):
            self.require_enabled(control)
            row = self.require(control, db, item_id, scope=self.scope, now=self.clock(), policy=load_policy())
            value = json.loads(row["payload"])
            return {"category": value["category"]} if row["kind"] == "project_reference" else value

    def erase_requested(self, request_id: str) -> dict:
        self.check_project()
        with self.access() as (control, db):
            now = self.clock()
            blocked = db.execute("SELECT sample_id FROM project_erasures WHERE request_id = ? AND project = ?",
                                 (request_id, self.scope)).fetchall()
            changed = sum(self.mark(control, db, item[0], "user_request", now) for item in blocked)
        if changed:
            self.audit_erasure("requested")
        return self.finish_erasures()
