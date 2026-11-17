"""Promotion automatique d'une politique synthétique sur preuves locales."""

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Callable
from uuid import UUID

from contracts.akasha_contracts.authz import authorize

from .experience import transaction
from .notes_evolution import audit
from .notes_link_promotion import canonical, digest, verify_signature
from .planning import ENVIRONMENT

STAGES = ("replay", "shadow", "limited")
Signer = Callable[[dict], str]


@dataclass(frozen=True)
class Policy:
    family: str
    parent: str
    candidate: str
    freeze_sha256: str
    replay: tuple[str, ...]
    shadow: tuple[str, ...]
    limited: str
    decision_limit_us: int
    min_wall_savings_ms: int | None = None

    def __post_init__(self):
        if (self.family not in ("route", "skill", "memory") or not self.parent or not self.candidate
                or self.candidate == self.parent or self.limited not in self.replay or not self.shadow
                or len(set(self.replay)) != len(self.replay) or len(set(self.shadow)) != len(self.shadow)
                or len(self.freeze_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.freeze_sha256)
                or type(self.decision_limit_us) is not int or self.decision_limit_us <= 0
                or (self.min_wall_savings_ms is not None and
                    (type(self.min_wall_savings_ms) is not int or self.min_wall_savings_ms <= 0))):
            raise ValueError("Politique d'évolution invalide.")

    def cases(self, stage: str) -> tuple[str, ...]:
        if stage == "replay":
            return self.replay
        if stage == "shadow":
            return self.shadow
        if stage == "limited":
            return (self.limited,)
        raise ValueError("Palier inconnu.")


@dataclass(frozen=True)
class SandboxScope:
    sandbox_id: str
    environment: str
    risk_class: str
    confinement_verified: bool
    synthetic: bool

    def __post_init__(self):
        UUID(self.sandbox_id)

    def allowed(self) -> bool:
        return (self.environment == ENVIRONMENT and self.risk_class in ("R0", "R1")
                and self.synthetic is True and self.confinement_verified is True
                and authorize({"risk_class": self.risk_class, "confinement_verified": True}) is None)


@dataclass(frozen=True)
class Observation:
    # Signaux du vérificateur et empreintes. Aucun état brut de l'application.
    sandbox_id: str
    case: str
    version: str
    input_sha256: str
    result_sha256: str
    safe: bool
    verified: bool
    decision_us: int
    wall_ms: int
    mismatches: tuple[str, ...] = ()

    def __post_init__(self):
        UUID(self.sandbox_id)
        for value in (self.input_sha256, self.result_sha256):
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError("Empreinte d'observation invalide.")
        if (type(self.safe) is not bool or type(self.verified) is not bool
                or type(self.decision_us) is not int or self.decision_us < 0
                or type(self.wall_ms) is not int or self.wall_ms < 0):
            raise ValueError("Mesures de l'observation invalides.")


class BoundedEvolution:
    """Un cycle par registre, une tentative par palier et une exposition limitée."""

    def __init__(self, path: Path, cycle: str, policy: Policy, public_key: str):
        self.path, self.cycle, self.policy, self.public_key = path, cycle, policy, public_key
        manifest = asdict(policy)
        if policy.min_wall_savings_ms is None:
            del manifest["min_wall_savings_ms"]
        self.identity = digest({"cycle": cycle, "policy": manifest, "public_key": public_key})

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=False)
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE cycle_identity (identity TEXT NOT NULL)")
            db.execute("INSERT INTO cycle_identity VALUES (?)", (self.identity,))
            db.execute("CREATE TABLE evolution_events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)")
            db.execute("CREATE TABLE attempts (stage TEXT PRIMARY KEY, scope_id TEXT UNIQUE NOT NULL, mode TEXT NOT NULL)")
            db.execute("""CREATE TABLE batch_trials (
                stage TEXT NOT NULL, case_id TEXT NOT NULL, route TEXT NOT NULL, sandbox TEXT UNIQUE NOT NULL,
                PRIMARY KEY (stage, case_id, route))""")
            db.execute("CREATE TABLE stage_proofs (position INTEGER PRIMARY KEY, stage TEXT UNIQUE, proof TEXT NOT NULL)")
            db.execute("CREATE TABLE rejected_proofs (stage TEXT PRIMARY KEY, proof TEXT NOT NULL)")
            db.execute("CREATE TABLE decisions (action TEXT PRIMARY KEY, document TEXT NOT NULL, signature TEXT NOT NULL)")
            db.execute("CREATE TABLE live_observations (proof_sha256 TEXT PRIMARY KEY, proof TEXT NOT NULL)")
            for table in ("cycle_identity", "evolution_events", "attempts", "batch_trials", "stage_proofs", "rejected_proofs",
                          "decisions", "live_observations"):
                for operation in ("UPDATE", "DELETE"):
                    db.execute(f"""CREATE TRIGGER freeze_{table}_{operation.lower()} BEFORE {operation} ON {table}
                                   BEGIN SELECT RAISE(ABORT, 'append-only'); END""")
            audit(db, self.cycle, "initialized", {"policy_sha256": self.identity, "parent": self.policy.parent})

    def _stage_digests(self, db) -> list[dict]:
        return [{"stage": stage, "sha256": digest(json.loads(proof))}
                for stage, proof in db.execute("SELECT stage, proof FROM stage_proofs ORDER BY position")]

    def _decisions(self, db) -> list[dict]:
        if db.execute("SELECT identity FROM cycle_identity").fetchall() != [(self.identity,)]:
            raise RuntimeError("Le registre ne correspond pas à la politique figée.")
        chain = []
        current = self.policy.parent
        stages = self._stage_digests(db)
        for action, encoded, signature in db.execute("SELECT action, document, signature FROM decisions ORDER BY rowid"):
            document = json.loads(encoded)
            wanted = "promote" if not chain else "rollback"
            target = self.policy.candidate if wanted == "promote" else self.policy.parent
            previous = digest(chain[-1]) if chain else None
            trigger = document["trigger_sha256"]
            if wanted == "promote":
                trigger_valid = (tuple(row["stage"] for row in stages) == STAGES and trigger == stages[-1]["sha256"])
            else:
                observation = db.execute("SELECT proof FROM live_observations WHERE proof_sha256 = ?", (trigger,)).fetchone()
                trigger_valid = observation is not None and digest(json.loads(observation[0])) == trigger
            if (len(chain) >= 2 or action != wanted or document["action"] != wanted
                    or document["from"] != current or document["to"] != target
                    or document["policy_sha256"] != self.identity or document["stages"] != stages
                    or document["previous_decision_sha256"] != previous or not trigger_valid
                    or not verify_signature(document, signature, self.public_key)):
                raise RuntimeError("Chaîne des décisions d'évolution invérifiable.")
            chain.append({"document": document, "signature": signature})
            current = target
        return chain

    def _current(self, chain: list[dict]) -> str:
        return chain[-1]["document"]["to"] if chain else self.policy.parent

    def active(self) -> str:
        with transaction(self.path) as db:
            db.execute("BEGIN")
            return self._current(self._decisions(db))

    def reserve(self, stage: str, scope: SandboxScope) -> bool:
        return self._reserve(stage, scope.sandbox_id, "sandbox", allowed=scope.allowed(), risk=scope.risk_class)

    def reserve_batch(self, stage: str, batch_id: str) -> bool:
        UUID(batch_id)
        return self._reserve(stage, batch_id, "batch", allowed=True, risk=None)

    def _reserve(self, stage: str, scope_id: str, mode: str, *, allowed: bool, risk: str | None) -> bool:
        self.policy.cases(stage)
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            chain = self._decisions(db)
            completed = tuple(row["stage"] for row in self._stage_digests(db))
            already = db.execute("SELECT 1 FROM attempts WHERE stage = ? OR scope_id = ?",
                                 (stage, scope_id)).fetchone() or db.execute(
                "SELECT 1 FROM batch_trials WHERE sandbox = ?", (scope_id,)).fetchone()
            if not allowed or chain or STAGES[len(completed):len(completed) + 1] != (stage,) or already:
                audit(db, self.cycle, "exposure_refused", {"stage": stage, "risk_class": risk, "scope_allowed": allowed})
                return False
            db.execute("INSERT INTO attempts VALUES (?, ?, ?)", (stage, scope_id, mode))
            audit(db, self.cycle, "stage_reserved", {"stage": stage, mode: scope_id})
            return True

    def admit_trial(self, stage: str, batch_id: str, scope: SandboxScope, case: str, version: str) -> bool:
        if not scope.allowed() or (case, version) not in self._expected(stage):
            return False
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if (self._decisions(db) or db.execute("SELECT scope_id, mode FROM attempts WHERE stage = ?", (stage,)).fetchone()
                    != (batch_id, "batch") or not self._pending(db, stage)
                    or db.execute("SELECT 1 FROM attempts WHERE scope_id = ?", (scope.sandbox_id,)).fetchone()):
                return False
            inserted = db.execute("INSERT OR IGNORE INTO batch_trials VALUES (?, ?, ?, ?)",
                                  (stage, case, version, scope.sandbox_id)).rowcount
            if inserted:
                audit(db, self.cycle, "trial_admitted", {"stage": stage, "case": case, "version": version,
                                                        "sandbox": scope.sandbox_id})
            return bool(inserted)

    def _usable(self, item: Observation) -> bool:
        return item.safe and not item.mismatches and item.decision_us <= self.policy.decision_limit_us

    def _expected(self, stage: str) -> set:
        versions = (self.policy.candidate,) if stage == "limited" else (self.policy.parent, self.policy.candidate)
        return {(case, v) for case in self.policy.cases(stage) for v in versions}

    def _saves_time(self, parent: dict, candidate: dict) -> bool:
        return (parent["verified"] and candidate["verified"] and parent["input_sha256"] == candidate["input_sha256"]
                and parent["result_sha256"] == candidate["result_sha256"]
                and parent["wall_ms"] - candidate["wall_ms"] >= self.policy.min_wall_savings_ms)

    def _measure(self, stage: str, receipts: tuple[Observation, ...]) -> dict:
        indexed = {(item.case, item.version): item for item in receipts}
        if len(indexed) != len(receipts) or set(indexed) != self._expected(stage):
            raise ValueError("Preuves du palier incomplètes ou dupliquées.")
        summary = {"qualified": True, "cases": {}}
        for case in self.policy.cases(stage):
            candidate = indexed[case, self.policy.candidate]
            parent = indexed.get((case, self.policy.parent))
            summary["qualified"] &= self._usable(candidate) and candidate.verified
            if parent is None:
                summary["cases"][case] = {"candidate_verified": candidate.verified}
                continue
            summary["qualified"] &= self._usable(parent) and parent.input_sha256 == candidate.input_sha256
            summary["cases"][case] = {"candidate_verified": candidate.verified, "parent_verified": parent.verified,
                                       "verified_gain": int(candidate.verified) - int(parent.verified),
                                       "wall_delta_ms": candidate.wall_ms - parent.wall_ms}
            if self.policy.min_wall_savings_ms is not None:
                savings = self._saves_time(asdict(parent), asdict(candidate))
                summary["cases"][case]["equivalent_and_faster"] = savings
                summary["qualified"] &= savings
        if stage == "replay" and self.policy.min_wall_savings_ms is None:
            summary["qualified"] &= sum(item["verified_gain"] for item in summary["cases"].values()) > 0
        return summary

    def _pending(self, db, stage: str, *, allow_rejected: bool = False) -> bool:
        completed = self._stage_digests(db)
        return (STAGES[len(completed):len(completed) + 1] == (stage,) and
                (allow_rejected or not db.execute("SELECT 1 FROM rejected_proofs WHERE stage = ?", (stage,)).fetchone()))

    def _parent_receipt(self, db, case: str) -> dict:
        proof, = db.execute("SELECT proof FROM stage_proofs WHERE stage = 'replay'").fetchone()
        receipt, = (item for item in json.loads(proof)["receipts"]
                    if item["case"] == case and item["version"] == self.policy.parent)
        return receipt

    def complete_stage(self, stage: str, scope: SandboxScope, receipts: tuple[Observation, ...], sign: Signer) -> dict:
        if not scope.allowed() or any(item.sandbox_id != scope.sandbox_id for item in receipts):
            raise PermissionError("Preuve hors bac autorisé.")
        return self._complete(stage, scope.sandbox_id, "sandbox", receipts, sign)

    def complete_batch(self, stage: str, batch_id: str, receipts: tuple[Observation, ...], sign: Signer) -> dict:
        return self._complete(stage, batch_id, "batch", receipts, sign)

    def _complete(self, stage: str, scope_id: str, mode: str, receipts: tuple[Observation, ...], sign: Signer) -> dict:
        proof = {"receipts": [asdict(item) for item in receipts], **self._measure(stage, receipts)}
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            chain = self._decisions(db)
            completed = self._stage_digests(db)
            if (chain or db.execute("SELECT scope_id, mode FROM attempts WHERE stage = ?", (stage,)).fetchone()
                    != (scope_id, mode) or not self._pending(db, stage, allow_rejected=True)):
                raise RuntimeError("Preuve sans réservation valide.")
            if mode == "batch":
                admitted = set(db.execute("SELECT case_id, route, sandbox FROM batch_trials WHERE stage = ?", (stage,)))
                if admitted != {(item.case, item.version, item.sandbox_id) for item in receipts}:
                    raise PermissionError("Les preuves ne correspondent pas aux bacs admis.")
            if stage == "limited":
                parent = self._parent_receipt(db, self.policy.limited)
                trial = proof["receipts"][0]
                measures = proof["cases"][self.policy.limited]
                measures["same_input"] = trial["input_sha256"] == parent["input_sha256"]
                proof["qualified"] &= measures["same_input"]
                if self.policy.min_wall_savings_ms is not None:
                    measures["equivalent_and_faster"] = self._saves_time(parent, trial)
                    proof["qualified"] &= measures["equivalent_and_faster"]
            encoded = canonical(proof).decode()
            rejected = db.execute("SELECT proof FROM rejected_proofs WHERE stage = ?", (stage,)).fetchone()
            if rejected is not None:
                if rejected[0] != encoded:
                    raise RuntimeError("Le palier refusé a consommé sa tentative.")
                return proof
            if not proof["qualified"]:
                db.execute("INSERT INTO rejected_proofs VALUES (?, ?)", (stage, encoded))
                audit(db, self.cycle, "stage_rejected", {"stage": stage, "proof_sha256": digest(proof)})
                return proof
            db.execute("INSERT INTO stage_proofs VALUES (?, ?, ?)", (len(completed) + 1, stage, encoded))
            audit(db, self.cycle, "stage_verified", {"stage": stage, "proof_sha256": digest(proof)})
            if stage == "limited":
                proof["decision"] = self._append_decision(db, chain, "promote", digest(proof), sign)
        return proof

    def select(self, scope: SandboxScope, case: str) -> str:
        if not scope.allowed():
            raise PermissionError("Sélection automatique hors périmètre.")
        return self.active() if case == self.policy.limited else self.policy.parent

    def observe(self, scope: SandboxScope, receipt: Observation, sign: Signer) -> dict:
        if (not scope.allowed() or receipt.sandbox_id != scope.sandbox_id or receipt.case != self.policy.limited
                or receipt.version not in (self.policy.parent, self.policy.candidate)):
            raise PermissionError("Observation post-promotion hors périmètre.")
        data = asdict(receipt)
        proof = digest(data)
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            chain = self._decisions(db)
            current = self._current(chain)
            if (not chain or db.execute("SELECT 1 FROM attempts WHERE scope_id = ?", (scope.sandbox_id,)).fetchone()
                    or db.execute("SELECT 1 FROM batch_trials WHERE sandbox = ?", (scope.sandbox_id,)).fetchone()):
                raise RuntimeError("Il faut une observation distincte des paliers.")
            if not db.execute("INSERT OR IGNORE INTO live_observations VALUES (?, ?)",
                              (proof, canonical(data).decode())).rowcount:
                return {"active": current, "duplicate": True}
            alarms = []
            parent = self._parent_receipt(db, receipt.case)
            same_input = parent["input_sha256"] == receipt.input_sha256
            attribution = {
                "same_input": same_input,
                "verified_gain": int(receipt.verified) - int(parent["verified"]) if same_input else None,
                "wall_delta_ms": receipt.wall_ms - parent["wall_ms"] if same_input else None,
                "decision_us": receipt.decision_us,
            }
            if not same_input:
                alarms.append("input_drift")
            if not receipt.safe or not receipt.verified or receipt.mismatches:
                alarms.append("verification")
            if receipt.decision_us > self.policy.decision_limit_us:
                alarms.append("decision_latency")
            if (receipt.version == self.policy.candidate and receipt.verified
                    and self.policy.min_wall_savings_ms is not None
                    and not self._saves_time(parent, data)):
                alarms.append("attributed_gain")
            audit(db, self.cycle, "observed", {"proof_sha256": proof, "version": receipt.version, "alerts": alarms,
                                                "attribution": attribution})
            result = {"active": current, "alerts": alarms, "attribution": attribution}
            if alarms and current == receipt.version == self.policy.candidate:
                result["decision"] = self._append_decision(db, chain, "rollback", proof, sign)
                result["active"] = self.policy.parent
        return result

    def _append_decision(self, db, chain: list[dict], action: str, proof: str, sign: Signer) -> dict:
        target = self.policy.candidate if action == "promote" else self.policy.parent
        document = {"version": 1, "family": self.policy.family, "action": action, "cycle": self.cycle,
                    "policy_sha256": self.identity, "from": self._current(chain), "to": target,
                    "previous_decision_sha256": digest(chain[-1]) if chain else None,
                    "stages": self._stage_digests(db), "trigger_sha256": proof}
        signature = sign(document)
        if not verify_signature(document, signature, self.public_key):
            raise RuntimeError("Signature de décision invalide.")
        db.execute("INSERT INTO decisions VALUES (?, ?, ?)", (action, canonical(document).decode(), signature))
        audit(db, self.cycle, action, {"from": document["from"], "to": target, "decision_sha256": digest(document)})
        return {"document": document, "signature": signature}
