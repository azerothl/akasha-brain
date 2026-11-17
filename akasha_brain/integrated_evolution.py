"""Arbitre les politiques de phase 6 à partir de leurs décisions signées."""

from contextlib import contextmanager
import json
from pathlib import Path
from collections.abc import Mapping

from .bounded_evolution import BoundedEvolution, Observation, SandboxScope, Signer
from .experience import transaction
from .notes_link_promotion import canonical, digest, verify_signature


class IntegratedEvolution:
    """Fige les registres associés et sérialise leurs changements d'autonomie."""

    def __init__(self, path: Path, cycles: Mapping[str, BoundedEvolution]):
        self.path = path.resolve()
        self._cycles = dict(cycles)
        if (not self._cycles or any(family != cycle.policy.family for family, cycle in self._cycles.items())
                or len({self.path, *(cycle.path.resolve() for cycle in self._cycles.values())}) != len(self._cycles) + 1):
            raise ValueError("Les registres d'évolution ne sont pas distincts ou ne correspondent pas à leurs familles.")
        self.identity = digest({family: cycle.identity for family, cycle in self._cycles.items()})
        self.parents = {family: cycle.policy.parent for family, cycle in self._cycles.items()}

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=False)
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("CREATE TABLE integrated_identity (identity TEXT PRIMARY KEY)")
            db.execute("INSERT INTO integrated_identity VALUES (?)", (self.identity,))
            for operation in ("UPDATE", "DELETE"):
                db.execute(f"""CREATE TRIGGER freeze_integrated_{operation.lower()} BEFORE {operation} ON integrated_identity
                               BEGIN SELECT RAISE(ABORT, 'append-only'); END""")
            self._state_locked(db)

    @contextmanager
    def _locked(self):
        with transaction(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT identity FROM integrated_identity").fetchall() != [(self.identity,)]:
                raise RuntimeError("Registres associés différents du gel intégré.")
            yield db

    def _state_locked(self, db) -> dict:
        rollbacks = {}
        signed = {}
        for family, cycle in self._cycles.items():
            with transaction(cycle.path) as local:
                local.execute("BEGIN")
                chain = cycle._decisions(local)
            if chain and chain[-1]["document"]["action"] == "rollback":
                rollbacks[family] = digest(chain[-1])
            signed[family] = cycle._current(chain)
        if db.execute("SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'operator_rollback'").fetchone():
            document, signature = db.execute("SELECT document, signature FROM operator_rollback WHERE id = 1").fetchone()
            document = json.loads(document)
            self._verify_operator(document, signature)
            rollbacks["operator"] = digest({"document": document, "signature": signature})
        return {"autonomy_phase": 3 if rollbacks else 6, "effective": dict(self.parents) if rollbacks else signed,
                "signed_active": signed, "rollback_proofs": rollbacks}

    def status(self) -> dict:
        with self._locked() as db:
            return self._state_locked(db)

    def _verify_operator(self, document: dict, signature: str) -> None:
        keys = {cycle.public_key for cycle in self._cycles.values()}
        if (len(keys) != 1 or document.get("action") != "operator_rollback" or document.get("version") != 1
                or document.get("identity") != self.identity or document.get("to") != self.parents
                or not verify_signature(document, signature, next(iter(keys)))):
            raise RuntimeError("Signature du retour arrière demandé invalide.")

    def request_rollback(self, sign: Signer) -> dict:
        """Abaisse l'autonomie sur demande locale, avec une décision distincte des alertes."""
        with self._locked() as db:
            before = self._state_locked(db)
            if before["autonomy_phase"] == 3:
                return before
            document = {"version": 1, "action": "operator_rollback", "identity": self.identity,
                        "from": before["effective"], "to": self.parents}
            signature = sign(document)
            self._verify_operator(document, signature)
            db.execute("CREATE TABLE operator_rollback (id INTEGER PRIMARY KEY CHECK(id=1), document TEXT, signature TEXT)")
            db.execute("INSERT INTO operator_rollback VALUES (1, ?, ?)", (canonical(document).decode(), signature))
            for operation in ("UPDATE", "DELETE"):
                db.execute(f"""CREATE TRIGGER freeze_operator_{operation.lower()} BEFORE {operation} ON operator_rollback
                               BEGIN SELECT RAISE(ABORT, 'append-only'); END""")
            return self._state_locked(db)

    @contextmanager
    def qualification(self, family: str):
        """Autorise une réservation ou une décision candidate dans le régime courant."""
        with self._locked() as db:
            if self._state_locked(db)["autonomy_phase"] != 6:
                raise PermissionError("Les promotions automatiques sont suspendues au niveau de phase 3.")
            yield self._cycles[family]

    def select(self, family: str, scope: SandboxScope, case: str) -> str:
        if not scope.allowed():
            raise PermissionError("Sélection intégrée hors périmètre.")
        with self._locked() as db:
            state = self._state_locked(db)
            cycle = self._cycles[family]
            return state["effective"][family] if case == cycle.policy.limited else cycle.policy.parent

    def observe(self, family: str, scope: SandboxScope, receipt: Observation, sign: Signer) -> dict:
        with self._locked() as db:
            self._state_locked(db)
            local = self._cycles[family].observe(scope, receipt, sign)
            return {"local": local, **self._state_locked(db)}
