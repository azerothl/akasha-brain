"""Découverte locale, qualification et reprise après une lacune de capacité."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import shutil
import subprocess

from contracts.akasha_contracts.errors import AkashaError, ErrorCode
from contracts.akasha_contracts.validate import validate

from . import ocr_recovery
from .experience import transaction
from .notes_evolution import lease
from .notes_sandbox import CHANNELS
from .planning import PlanningError
from .project_common import ProjectError

PROVIDERS = {ocr_recovery.CAPABILITY: ocr_recovery}
KNOWN_GAPS = {"image.generate", *PROVIDERS}
SANDBOX_ERRORS = (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired, PlanningError)


def verified(proof: dict) -> bool:
    return (proof.get("status") == "passed" and proof.get("sandbox_stopped") is True
            and proof.get("read_only_input") is True and proof.get("guest_exit_code") == 0x4700
            and proof.get("channel_probe") in (0x410F, 0x411F)
            and list(CHANNELS) == proof.get("disabled_channels"))


def installed_image_engines() -> list[str]:
    engines = [label for command, label in (("sd-cli.exe", "Stable Diffusion CLI"), ("comfy.exe", "Comfy CLI"))
               if shutil.which(command)]
    try:
        version("diffusers")
    except PackageNotFoundError:
        pass
    else:
        engines.append("Diffusers")
    return engines


@dataclass(frozen=True)
class Recovery:
    database: Path
    runtime: Path | None
    progress: Callable[[str], None]
    cancelled: Callable[[], bool]

    def prepare_db(self, db):
        db.execute("CREATE TABLE IF NOT EXISTS gap_reports (capability TEXT PRIMARY KEY, report TEXT NOT NULL)")
        db.execute("""CREATE TABLE IF NOT EXISTS local_capabilities (
            capability TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, proof TEXT NOT NULL
        )""")

    def record(self, capability: str, status: str, events: list[str], *, reason=None, fingerprint=None,
               proof=None, retire: bool = False, engines=None):
        data = {"capability": capability, "status": status, "events": events,
                "updated_at": datetime.now(timezone.utc).isoformat()}
        if reason is not None:
            data["reason"] = reason
        if fingerprint is not None:
            data["candidate_sha256"] = fingerprint
        if engines is not None:
            data["engines_found"] = engines
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
            engines = None
            reason = "no_compatible_adapter"
            if capability == "image.generate":
                engines = installed_image_engines()
                if engines:
                    message = "J’ai repéré " + ", ".join(engines) + ". Une intégration de génération reste à qualifier."
                else:
                    reason = "no_supported_image_engine_detected"
                    message = ("J’ai recherché les moteurs d’images locaux connus (Stable Diffusion CLI, Comfy CLI et Diffusers). "
                               "La génération est en attente d’un moteur compatible.")
            self.record(capability, "waiting", events, reason=reason, engines=engines)
            raise PlanningError(AkashaError(
                missing.code, message,
                {**missing.details, "recovery": "waiting"},
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
