"""Promotion signée du candidat Notes dans un registre de qualification isolé."""

from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import subprocess
from tempfile import TemporaryDirectory

from .experience import transaction
from .notes_evolution import active_workflow, audit
from .planning import ENVIRONMENT

STAGES = ("replay", "shadow_parent", "shadow_candidate", "limited")
PRINCIPAL = "akasha-notes-link-test"
NAMESPACE = "akasha.notes-link.decision.v1"
KEY_FORMAT = re.compile(r"ssh-ed25519 [A-Za-z0-9+/=]+")


def canonical(document) -> bytes:
    return json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def digest(document) -> str:
    return sha256(canonical(document)).hexdigest()


def ssh_keygen(arguments, data=None):
    executable = shutil.which("ssh-keygen")
    if executable is None:
        raise RuntimeError("OpenSSH est requis pour vérifier les décisions signées.")
    return subprocess.run([executable, *arguments], input=data, capture_output=True, timeout=20,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


@contextmanager
def disposable_signer():
    with TemporaryDirectory(prefix="akasha-notes-signer-") as directory:
        key = Path(directory) / "signer"
        generated = ssh_keygen(["-q", "-t", "ed25519", "-N", "", "-C", PRINCIPAL, "-f", str(key)])
        if generated.returncode != 0:
            raise RuntimeError("La création de la clé Ed25519 de test a échoué.")
        public_key = " ".join(key.with_suffix(".pub").read_text(encoding="ascii").split()[:2])

        def sign(document) -> str:
            result = ssh_keygen(["-Y", "sign", "-f", str(key), "-n", NAMESPACE], canonical(document))
            if result.returncode != 0:
                raise RuntimeError("La signature de la décision a échoué.")
            return result.stdout.decode("ascii")

        yield public_key, sign


def verify_signature(document, signature: str, public_key: str) -> bool:
    if not KEY_FORMAT.fullmatch(public_key):
        return False
    with TemporaryDirectory(prefix="akasha-notes-verify-") as directory:
        root = Path(directory)
        signers, proof = root / "allowed_signers", root / "decision.sig"
        signers.write_text(f"{PRINCIPAL} {public_key}\n", encoding="ascii")
        proof.write_text(signature, encoding="ascii", newline="\n")
        result = ssh_keygen(["-Y", "verify", "-f", str(signers), "-I", PRINCIPAL, "-n", NAMESPACE,
                             "-s", str(proof)], canonical(document))
        return result.returncode == 0


class NotesLinkPromotion:
    def __init__(self, path: Path, cycle_id: str, graphs: dict, freeze_sha256: str, reference_sha256: str, public_key: str):
        self.path = path
        self.cycle_id = cycle_id
        self.graphs = graphs
        self.parent, self.candidate = (graphs[arm]["graph_id"] for arm in ("parent", "candidate"))
        self.freeze_sha256 = freeze_sha256
        self.reference_sha256 = reference_sha256
        self.public_key = public_key

    def initialize(self) -> None:
        self.path.touch(exist_ok=False)
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE workflow_versions (id TEXT PRIMARY KEY, parent TEXT, plan TEXT NOT NULL)")
            db.execute("CREATE TABLE active_workflow (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), workflow TEXT)")
            db.execute("CREATE TABLE evolution_events (seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, digest TEXT NOT NULL)")
            db.execute("CREATE TABLE link_trials (position INTEGER PRIMARY KEY, stage TEXT UNIQUE, proof TEXT NOT NULL)")
            db.execute("CREATE TABLE link_decisions (action TEXT PRIMARY KEY, document TEXT NOT NULL, signature TEXT NOT NULL)")
            db.execute("CREATE TABLE limited_exposure (singleton INTEGER PRIMARY KEY CHECK (singleton = 1))")
            for table in ("evolution_events", "workflow_versions", "link_trials", "link_decisions"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"""CREATE TRIGGER freeze_{table}_{action.lower()} BEFORE {action} ON {table}
                                   BEGIN SELECT RAISE(ABORT, 'append-only'); END""")
            db.executemany("INSERT INTO workflow_versions VALUES (?, ?, ?)", [
                (self.parent, None, canonical(self.graphs["parent"]).decode()),
                (self.candidate, self.parent, canonical(self.graphs["candidate"]).decode()),
            ])
            db.execute("INSERT INTO active_workflow VALUES (1, ?)", (self.parent,))
            audit(db, self.cycle_id, "initialized", {"parent": self.parent, "candidate": self.candidate,
                                                    "freeze_sha256": self.freeze_sha256, "public_key": self.public_key})

    def active(self) -> str:
        with transaction(self.path) as db:
            db.execute("BEGIN")
            current = active_workflow(db)
            latest = db.execute("SELECT document, signature FROM link_decisions ORDER BY rowid DESC LIMIT 1").fetchone()
            if latest is None and current == self.parent:
                return current
            if latest is not None:
                decision = json.loads(latest[0])
                if decision["to"] == current and verify_signature(decision, latest[1], self.public_key):
                    return current
            raise RuntimeError("Le graphe actif ne correspond pas à une décision vérifiée.")

    def trials(self, db) -> dict:
        return {stage: json.loads(proof) for stage, proof in db.execute("SELECT stage, proof FROM link_trials ORDER BY position")}

    def limited_route(self, environment: str, *, eligible: bool) -> str:
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if active_workflow(db) != self.parent:
                raise RuntimeError("Le parent doit être actif avant l'exposition limitée.")
            spent = db.execute("SELECT 1 FROM limited_exposure").fetchone()
            if environment != ENVIRONMENT or not eligible or spent or tuple(self.trials(db)) != STAGES[:-1]:
                return self.parent
            db.execute("INSERT INTO limited_exposure VALUES (1)")
            audit(db, self.cycle_id, "limited_admitted", {"environment": ENVIRONMENT, "maximum": 1})
            return self.candidate

    def record_trial(self, stage: str, proof: dict) -> None:
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            trials = self.trials(db)
            graph = self.parent if stage == "shadow_parent" else self.candidate
            if (STAGES[len(trials):len(trials) + 1] != (stage,) or active_workflow(db) != self.parent
                    or not proof.get("verified") or proof.get("graph_id") != graph or not proof.get("sandbox_id")
                    or any(previous["sandbox_id"] == proof["sandbox_id"] for previous in trials.values())):
                raise RuntimeError("La preuve ou l'ordre des paliers est incompatible avec la promotion.")
            if stage == "shadow_candidate" and proof["outcome_sha256"] != trials["shadow_parent"]["outcome_sha256"]:
                raise RuntimeError("Le candidat et le parent divergent en shadow.")
            if stage == "limited" and not db.execute("SELECT 1 FROM limited_exposure").fetchone():
                raise RuntimeError("Le palier limité exige une admission.")
            db.execute("INSERT INTO link_trials VALUES (?, ?, ?)", (len(trials) + 1, stage, canonical(proof).decode()))
            audit(db, self.cycle_id, "trial_verified", {"stage": stage, "proof_sha256": digest(proof)})

    def decision(self, db, action: str) -> dict:
        trials = self.trials(db)
        prior = db.execute("SELECT action, document, signature FROM link_decisions ORDER BY rowid DESC LIMIT 1").fetchone()
        if action == "promote" and prior is None and tuple(trials) == STAGES:
            source, target = self.parent, self.candidate
        elif action == "rollback" and prior is not None and prior[0] == "promote":
            source, target = self.candidate, self.parent
        else:
            raise RuntimeError("Transition incompatible avec le journal des paliers.")
        if active_workflow(db) != source:
            raise RuntimeError("Le graphe actif a changé.")
        plans = {graph: sha256(plan.encode()).hexdigest() for graph, plan in db.execute("SELECT id, plan FROM workflow_versions")}
        if plans != {plan["graph_id"]: digest(plan) for plan in self.graphs.values()}:
            raise RuntimeError("Les plans enregistrés ne correspondent plus au gel.")
        previous = None
        if prior is not None:
            parent_decision = json.loads(prior[1])
            if not verify_signature(parent_decision, prior[2], self.public_key):
                raise RuntimeError("La décision de promotion antérieure est invérifiable.")
            previous = digest({"document": parent_decision, "signature": prior[2]})
        return {
            "version": 1, "action": action, "cycle": self.cycle_id, "environment": ENVIRONMENT,
            "from": source, "to": target, "plans": plans, "freeze_sha256": self.freeze_sha256,
            "reference_sha256": self.reference_sha256, "previous_decision_sha256": previous,
            "trials": [{"stage": stage, "proof_sha256": digest(proof)} for stage, proof in trials.items()],
        }

    def prepare(self, action: str) -> dict:
        with transaction(self.path) as db:
            db.execute("BEGIN")
            return self.decision(db, action)

    def apply(self, document: dict, signature: str) -> None:
        snapshot = canonical(document)
        document = json.loads(snapshot)
        if not verify_signature(document, signature, self.public_key):
            raise RuntimeError("Signature Ed25519 invalide.")
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if document != self.decision(db, document["action"]):
                raise RuntimeError("La décision signée ne correspond pas à l'état du registre.")
            db.execute("INSERT INTO link_decisions VALUES (?, ?, ?)",
                       (document["action"], snapshot.decode(), signature))
            db.execute("UPDATE active_workflow SET workflow = ? WHERE singleton = 1", (document["to"],))
            audit(db, self.cycle_id, document["action"], {"from": document["from"], "to": document["to"],
                                                       "decision_sha256": digest(document)})
