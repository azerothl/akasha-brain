"""Découverte locale, qualification et reprise après une lacune de capacité."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

from contracts.akasha_contracts.errors import AkashaError, ErrorCode
from contracts.akasha_contracts.validate import validate

from . import image_assets, image_recovery, ocr_recovery
from .experience import transaction
from .gap_resolution import AUDIO_FORMATS, GapReview, TRANSCRIPTION, transcription_proposal
from .image_windows import verifies_windows as verified
from .notes_evolution import lease
from .planning import PlanningError
from .project_approval import new_request, require_fresh
from .project_common import ProjectError

PROVIDERS = {ocr_recovery.CAPABILITY: ocr_recovery}
KNOWN_GAPS = set(PROVIDERS)
SANDBOX_ERRORS = (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired, PlanningError)


@dataclass(frozen=True)
class Recovery:
    database: Path
    runtime: Path | None
    progress: Callable[[str], None]
    cancelled: Callable[[], bool]
    image_prompt: Callable[[str], str] | None = None

    def prepare_db(self, db):
        db.execute("CREATE TABLE IF NOT EXISTS gap_reports (capability TEXT PRIMARY KEY, report TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS local_capabilities (
            capability TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, proof TEXT NOT NULL
        )""")

    def record(self, capability: str, status: str, events: list[str], *, reason=None, fingerprint=None,
               proof=None, retire: bool = False, diagnostic=None):
        data = {"capability": capability, "status": status, "events": events,
                "updated_at": datetime.now(timezone.utc).isoformat()}
        if reason is not None:
            data["reason"] = reason
        if fingerprint is not None:
            data["candidate_sha256"] = fingerprint
        if diagnostic is not None:
            data["diagnostic"] = diagnostic
        with transaction(self.database) as db:
            self.prepare_db(db)
            db.execute("INSERT OR REPLACE INTO gap_reports VALUES (?, ?)", (capability, json.dumps(data)))
            if proof is not None:
                db.execute("INSERT OR REPLACE INTO local_capabilities VALUES (?, ?, ?)",
                           (capability, fingerprint, json.dumps(proof)))
            elif retire:
                db.execute("DELETE FROM local_capabilities WHERE capability = ?", (capability,))

    def stored(self, capability):
        with transaction(self.database) as db:
            self.prepare_db(db)
            active = db.execute("SELECT fingerprint, proof FROM local_capabilities WHERE capability = ?",
                                (capability,)).fetchone()
        return (active[0], json.loads(active[1])) if active is not None else None

    def checkpoint(self):
        if self.cancelled():
            raise InterruptedError("Demande annulée.")

    def integration_review(self, project: Path, context: str) -> GapReview | None:
        self.checkpoint()
        if context not in AUDIO_FORMATS:
            raise ValueError("Contexte de proposition inconnu.")
        if self.database.resolve().is_relative_to(project):
            raise PlanningError(AkashaError(ErrorCode.PERMISSION_DENIED, "Le registre de reprise doit être hors du projet."))
        with transaction(self.database) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS integration_contexts (
                family TEXT NOT NULL, context TEXT NOT NULL, PRIMARY KEY(family, context)
            )""")
            db.execute("INSERT OR IGNORE INTO integration_contexts VALUES (?, ?)", (TRANSCRIPTION, context))
            if db.execute("SELECT COUNT(*) FROM integration_contexts WHERE family = ?", (TRANSCRIPTION,)).fetchone()[0] < 2:
                return None
            request = new_request()
            db.execute("""CREATE TABLE IF NOT EXISTS integration_requests (
                id TEXT PRIMARY KEY, expires_at TEXT NOT NULL, consumed INTEGER NOT NULL
            )""")
            db.execute("DELETE FROM integration_requests WHERE expires_at <= ?", (request["issued_at"],))
            db.execute("INSERT INTO integration_requests VALUES (?, ?, 0)", (request["id"], request["expires_at"]))
        self.record(TRANSCRIPTION, "awaiting_approval", ["missing", "local_discovery", "recurrent_gap"])
        return GapReview(request["id"])

    def prepare_integration(self, review: GapReview, *, approved: bool) -> dict:
        if approved is not True:
            raise PlanningError(AkashaError(ErrorCode.APPROVAL_REQUIRED, "Accord requis pour préparer la proposition."))
        self.checkpoint()
        with transaction(self.database) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT expires_at, consumed FROM integration_requests WHERE id = ?",
                             (review.request_id,)).fetchone()
            if row is None or row[1]:
                raise PlanningError(AkashaError(ErrorCode.APPROVAL_REQUIRED, "La demande d’accord n’est plus disponible."))
            require_fresh(datetime.fromisoformat(row[0]))
            contexts = tuple(row[0] for row in db.execute(
                "SELECT context FROM integration_contexts WHERE family = ? ORDER BY context", (TRANSCRIPTION,)))
            db.execute("UPDATE integration_requests SET consumed = 1 WHERE id = ?", (review.request_id,))
        proposal = transcription_proposal(contexts)
        self.record(TRANSCRIPTION, "construction_proposed", ["missing", "recurrent_gap", "operator_approved"],
                    diagnostic=proposal)
        return proposal

    def generate_image(self, prompt: str, project: Path | None,
                       consent: tuple[image_assets.DownloadReview, str] | None):
        cache = self.database.parent / "image-engine"
        if project is not None and (self.database.is_relative_to(project) or cache.resolve().is_relative_to(project)):
            raise PlanningError(AkashaError(ErrorCode.PERMISSION_DENIED,
                "Le cache du moteur doit être stocké hors du projet sélectionné."))
        events = ["missing", "local_discovery"]
        capability = image_recovery.CAPABILITY
        with lease(self.database, cycle=True):
            self.checkpoint()
            if consent is not None:
                approval, receipt = consent
                if approval.directory != cache.resolve():
                    raise PlanningError(AkashaError(ErrorCode.PERMISSION_DENIED, "Accord lié à un autre cache."))
                self.progress(f"Je télécharge {approval.artifact.name} et je vérifie son empreinte.")
                image_assets.download(approval, receipt, self.checkpoint)
                events.append("artifact_verified")
            candidate = image_recovery.discover(cache, self.runtime)
            if isinstance(candidate, image_assets.DownloadReview):
                self.record(capability, "waiting", events + ["approval_requested"], reason=candidate.artifact.filename)
                return candidate
            active = self.stored(capability)
            if active is None or active[0] != candidate.fingerprint or not image_recovery.verifies(candidate, active[1]):
                self.record(capability, "qualifying", events + ["candidate", "qualification"], retire=True,
                            fingerprint=candidate.fingerprint)
                self.progress(f"Je qualifie SD-Turbo sur une image de référence dans {candidate.backend.label}, hors ligne.")
                try:
                    qualification = image_recovery.run(candidate, image_recovery.QUALIFICATION, self.checkpoint)
                    self.checkpoint()
                    if not image_recovery.verifies(candidate, qualification.proof):
                        raise RuntimeError("La preuve de génération qualifiée est incomplète.")
                except SANDBOX_ERRORS:
                    self.record(capability, "failed", events + ["candidate", "qualification"], reason="qualification_failed")
                    raise
                events.extend(("candidate", "qualification", "activated"))
                self.record(capability, "activated", events, fingerprint=candidate.fingerprint,
                            proof=qualification.proof)
                self.progress("SD-Turbo est qualifié. Je reprends votre demande dans un nouveau bac.")
            else:
                events = ["reused"]
                self.progress(f"Je réutilise SD-Turbo hors ligne dans {candidate.backend.label}.")
            try:
                if self.image_prompt is not None:
                    prompt = self.image_prompt(prompt)
                    self.checkpoint()
                result = image_recovery.run(candidate, prompt, self.checkpoint)
                self.checkpoint()
                if not image_recovery.verifies(candidate, result.proof):
                    raise ProjectError(AkashaError(ErrorCode.CONTRACT_POSTCONDITION_FAILED,
                                       "Le PNG ne porte pas de preuve d’exécution isolée valide."))
            except ProjectError as error:
                if error.error.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED:
                    self.record(capability, "failed", events + ["rolled_back"], reason="execution_failed", retire=True)
                raise
            self.record(capability, "resumed", events + ["resumed"], fingerprint=candidate.fingerprint)
            return result

    def activate(self, missing: AkashaError, project: Path | None) -> tuple[dict, ocr_recovery.Candidate, list[str]]:
        self.checkpoint()
        if project is not None and self.database.is_relative_to(project):
            raise PlanningError(AkashaError(ErrorCode.PERMISSION_DENIED,
                "Le registre d’évolution doit être stocké hors du projet sélectionné."))
        name = missing.details.get("capability")
        capability = name if isinstance(name, str) and name in KNOWN_GAPS else "unclassified"
        provider = PROVIDERS.get(capability)
        events = ["missing", "local_discovery"]
        if provider is None:
            message = missing.message + " J’ai vérifié les intégrations locales et consigné la lacune."
            self.record(capability, "missing", events, reason="no_compatible_adapter")
            raise PlanningError(AkashaError(
                missing.code, message,
                {**missing.details, "recovery": "missing"},
            ))

        with lease(self.database, cycle=True):
            try:
                candidate = provider.discover(self.runtime)
            except ProjectError as error:
                self.record(capability, "waiting", events, reason=error.error.details.get("reason", "missing_artifact"),
                            retire=True)
                raise PlanningError(error.error) from error
            self.checkpoint()
            active = self.stored(capability)
            if active is not None and active[0] == candidate.fingerprint and verified(active[1]):
                self.progress("Je réutilise la capacité RapidOCR précédemment qualifiée.")
                return provider.MANIFEST, candidate, ["reused"]
            if active is not None:
                events.append("retired")
                self.record(capability, "candidate", events, fingerprint=candidate.fingerprint, retire=True)
            if errors := validate(provider.MANIFEST, "CapabilityManifest"):
                raise PlanningError(errors[0])
            events.extend(("candidate", "qualification"))
            self.record(capability, "qualifying", events, fingerprint=candidate.fingerprint)
            self.progress("J’ai trouvé RapidOCR sur ce poste. Je teste son intégration dans Windows Sandbox sur deux images synthétiques.")
            try:
                proof = provider.run(candidate, self.cancelled)
                self.checkpoint()
            except InterruptedError:
                self.record(capability, "cancelled", events)
                raise
            except SANDBOX_ERRORS as error:
                terminal = isinstance(error, ProjectError) and error.error.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED
                self.record(capability, "failed" if terminal else "waiting", events,
                            reason="qualification_failed" if terminal else "sandbox_unavailable",
                            fingerprint=candidate.fingerprint)
                raise PlanningError(AkashaError(ErrorCode.CAPABILITY_UNAVAILABLE,
                    "L’intégration OCR n’a pas été activée. La qualification dans Windows Sandbox a été interrompue.",
                    {"capability": capability, "recovery": "waiting"})) from error
            if not verified(proof):
                self.record(capability, "failed", events, reason="invalid_proof", fingerprint=candidate.fingerprint)
                raise PlanningError(AkashaError(ErrorCode.CONTRACT_POSTCONDITION_FAILED,
                    "La qualification OCR n’a pas fourni de preuve de confinement et de réussite."))
            events.append("activated")
            self.record(capability, "activated", events, fingerprint=candidate.fingerprint, proof=proof)
            self.progress("Capacité RapidOCR validée. Je reprends votre demande dans un nouveau bac.")
            return provider.MANIFEST, candidate, events

    def resume(self, capability, candidate, events, project, target):
        provider = PROVIDERS[capability]
        self.checkpoint()
        image = provider.read_input(project, target)
        with lease(self.database, cycle=True):
            active = self.stored(capability)
            if active is None or active[0] != candidate.fingerprint or not verified(active[1]):
                raise PlanningError(AkashaError(ErrorCode.CAPABILITY_UNAVAILABLE,
                    "L’activation OCR a changé. Relancez la demande depuis le registre courant."))
            try:
                result = provider.run(candidate, self.cancelled, image)
                self.checkpoint()
                if not verified(result) or not isinstance(result.get("exported"), str):
                    raise ProjectError(AkashaError(ErrorCode.CONTRACT_POSTCONDITION_FAILED,
                        "Le résultat OCR ne porte pas de preuve d’isolation valide."))
            except (InterruptedError, PlanningError):
                raise
            except ProjectError as error:
                if error.error.code == ErrorCode.CONTRACT_POSTCONDITION_FAILED:
                    self.record(capability, "failed", events + ["rolled_back"], reason="execution_failed",
                                fingerprint=candidate.fingerprint, retire=True)
                    self.progress("Le moteur n’a pas passé le contrôle à l’usage. J’ai retiré cette activation.")
                raise
            except SANDBOX_ERRORS as error:
                self.record(capability, "waiting", events, reason="execution_interrupted", fingerprint=candidate.fingerprint)
                raise PlanningError(AkashaError(ErrorCode.ENVIRONMENT_OBSERVATION_FAILED,
                    "La lecture OCR confinée a été interrompue.")) from error
            self.record(capability, "resumed", events + ["resumed"], fingerprint=candidate.fingerprint)
            return result["exported"]
