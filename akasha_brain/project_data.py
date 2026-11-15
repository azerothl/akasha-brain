"""Périmètre et inventaire des données d'évolution d'un projet local."""

from datetime import datetime, timezone
from pathlib import Path

from contracts.akasha_contracts.errors import ErrorCode

from .evolution_consent import ReuseScope, check_reuse, grant, instant, read_consents, revoke
from .experience import transaction
from .project_backup_vault import table_exists
from .project_common import project_scope, reject
from .project_evolution import ARTIFACTS, content_path, erase, registry_path


class ProjectData:
    def __init__(self, project: Path, registry: Path):
        self.project = project.resolve(strict=True)
        self.scope = project_scope(self.project)
        self.registry = registry_path(self.project, registry, require_existing=False)

    def check_project(self) -> None:
        if project_scope(self.project) != self.scope:
            reject(ErrorCode.PERMISSION_DENIED, "L’identité du dossier a changé. Sélectionnez à nouveau le projet.")
        if registry_path(self.project, self.registry, require_existing=False) != self.registry:
            reject(ErrorCode.PERMISSION_DENIED, "L’emplacement du registre a changé.")

    def grant(self, categories: list[str]) -> dict:
        self.check_project()
        if not categories or set(categories) - ARTIFACTS.keys():
            reject(ErrorCode.PERMISSION_DENIED, "Sélectionnez les catégories prises en charge par le parcours projet.")
        return grant(self.registry, self.scope, categories)

    def revoke(self, consent_id: str) -> dict:
        self.check_project()
        return revoke(self.registry, consent_id, project=self.scope)

    def erase(self, sample_id: str) -> dict:
        self.check_project()
        return erase(self.project, self.registry, sample_id)

    def inventory(self) -> dict:
        self.check_project()
        state = {"consents": [], "copies": [], "erasures": []}
        if not self.registry.is_file():
            return state
        now = datetime.now(timezone.utc)
        with transaction(self.registry) as grants:
            grants.execute("PRAGMA busy_timeout = 150")
            grants.execute("BEGIN")
            for consent in read_consents(grants, project=self.scope):
                expires = consent.get("expires_at")
                if consent["status"] == "active" and expires and now >= instant(expires):
                    consent["status"] = "expired"
                state["consents"].append(consent)
            if table_exists(grants, "project_erasures"):
                state["erasures"] = [
                    {"request_id": request, "sample_id": sample, "requested_at": date, "status": status,
                     "reason": reason, "count": count}
                    for request, sample, date, status, reason, count in grants.execute("""
                        SELECT request_id, MIN(sample_id), requested_at, state, reason, COUNT(*)
                        FROM project_erasures WHERE project = ?
                        GROUP BY request_id, requested_at, state, reason ORDER BY requested_at DESC
                    """, (self.scope,))
                ]
                blocked = grants.execute(
                    "SELECT sample_id, source_id FROM project_erasures WHERE project = ?", (self.scope,)).fetchall()
            else:
                blocked = []
            blocked_copies = {sample for sample, _ in blocked}
            blocked_sources = {source for _, source in blocked if source is not None}
            contents = content_path(self.project, self.registry)
            if contents.is_file():
                with transaction(contents) as db:
                    db.execute("PRAGMA busy_timeout = 150")
                    if table_exists(db, "samples"):
                        for sample, category, consent, expires_at, source in db.execute("""
                            SELECT sample_id, category, consent_id, expires_at, json_extract(manifest, '$.source_id')
                            FROM samples
                            WHERE project = ? ORDER BY created_at DESC
                        """, (self.scope,)):
                            denied = check_reuse(grants, (ReuseScope(self.scope, category, consent, "project", False),),
                                                 now=now)
                            if sample in blocked_copies or source in blocked_sources:
                                status = "content_erasure_requested"
                            elif now >= instant(expires_at):
                                status = "content_expired"
                            else:
                                status = denied.details["reason"] if denied else "available"
                            state["copies"].append({"sample_id": sample, "category": category,
                                                    "expires_at": expires_at, "status": status})
        return state
