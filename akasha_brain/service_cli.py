"""Configurer les services tiers du registre Akasha et appeler leurs opérations."""

import argparse
from getpass import getpass
import json
from pathlib import Path
import sqlite3
import sys
from uuid import UUID

from .conversation_sessions import SessionStore
from .conversation_vault import SessionVault, clear
from .desktop_settings import app_directory
from .memory_store import MemoryRefusal
from .service_connections import Connections
from .service_registry import DEFAULT_REGISTRY, MAX_BYTES, ServiceError, load_registry
from .vault_windows import KeyStoreUnavailable


def parser():
    installed = app_directory() / "service-adapters.json"
    cli = argparse.ArgumentParser(description=__doc__, epilog=(
        "L’adaptateur HTTPS accepte les services publics et les clés API Bearer. "
        "renew prolonge la permission locale. OAuth, ses jetons de rafraîchissement et la rotation "
        "des clés chez le fournisseur sont hors du périmètre de cette version."))
    cli.add_argument("--directory", type=Path, default=app_directory() / "runs",
                     help="Dossier du coffre et des sessions, par défaut celui du bureau Akasha.")
    cli.add_argument("--registry", type=Path, default=installed if installed.exists() else DEFAULT_REGISTRY,
                     help=f"Registre JSON de l’opérateur. Au démarrage, lecture de {installed} s’il existe, "
                          "sinon des deux déclarations fournies.")
    actions = cli.add_subparsers(dest="action", required=True)
    actions.add_parser("list", help="Lister les services, leurs opérations, permissions et schémas.")
    actions.add_parser("session", help="Créer une session locale.")
    grant = actions.add_parser("connect", help="Accorder les seules portées indiquées à une identité.")
    grant.add_argument("service")
    grant.add_argument("--destination", required=True, help="Origine HTTPS déclarée dans list.")
    grant.add_argument("--certificate", type=Path, required=True, help="Certificat PEM public du fournisseur.")
    grant.add_argument("--identity", required=True, help="Compte du fournisseur ou public.")
    grant.add_argument("--scope", action="append", required=True, help="Une opération, option répétable.")
    grant.add_argument("--key-stdin", action="store_true", help="Lire la clé API sur un canal d’entrée privé.")
    grant.add_argument("--minutes", required=True, type=int)
    status = actions.add_parser("status")
    renew = actions.add_parser("renew", help="Renouveler les mêmes portées et la même identité.")
    renew.add_argument("--minutes", required=True, type=int)
    revoke = actions.add_parser("revoke", aliases=["disconnect"], help="Révoquer et effacer la clé du coffre.")
    call = actions.add_parser("call", help="Exécuter une opération. Toute publication exige un accord distinct.")
    call.add_argument("operation")
    call.add_argument("--input", default="{}", help="Objet JSON conforme au schéma de l’opération.")
    for sub in (grant, status, renew, revoke, call):
        sub.add_argument("--session", required=True, type=UUID)
    for sub in (status, renew, revoke, call):
        sub.add_argument("--connection", required=True, type=UUID)
    return cli


def approval(preview):
    print(json.dumps(preview, ensure_ascii=True), file=sys.stderr)
    print("Autoriser cette écriture ? Saisissez PUBLIER pour confirmer.", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip() == "PUBLIER"


def egress(preview):
    print(json.dumps(preview, ensure_ascii=True), file=sys.stderr)
    print("Autoriser cet envoi HTTPS unique ? Saisissez ENVOYER.", file=sys.stderr, flush=True)
    return sys.stdin.readline().strip() == "ENVOYER"


def execute(args):
    if args.action == "list":
        return [svc.describe() for svc in load_registry(args.registry).values()]
    sessions = SessionStore(args.directory / "conversation-sessions.sqlite")
    if args.action == "session":
        return {"session": str(sessions.create())}
    connections = Connections(SessionVault(args.directory, sessions), registry_path=args.registry)
    if args.action == "connect":
        service = connections.provider(args.service)
        secret = None
        try:
            certificate = args.certificate.read_text(encoding="ascii")
            if service.authenticated:
                if args.key_stdin:
                    secret = bytearray(sys.stdin.buffer.readline(2563).rstrip(b"\r\n"))
                elif sys.stdin.isatty():
                    secret = bytearray(getpass("Clé API : "), "ascii")
                else:
                    raise ServiceError("private_input_required")
            grant = connections.authorize(args.session, args.service, origin=args.destination, identity=args.identity,
                                         scopes=args.scope, minutes=args.minutes, certificate=certificate, secret=secret)
        finally:
            if secret is not None:
                clear(secret)
    else:
        grant = str(args.connection)
        if args.action == "call":
            if len(args.input) > MAX_BYTES:
                raise ServiceError("budget_exceeded")
            try:
                data = json.loads(args.input)
            except (ValueError, RecursionError):
                raise ServiceError("input_schema") from None
            return connections.call(args.session, grant, args.operation, data, approve_egress=egress,
                                    approve_effect=approval)
        if args.action == "renew":
            connections.renew(args.session, grant, args.minutes)
        if args.action in ("revoke", "disconnect"):
            connections.revoke(args.session, grant)
    return connections.status(args.session, grant)


def main():
    args = parser().parse_args()
    try:
        print(json.dumps(execute(args), ensure_ascii=True))
    except (ServiceError, MemoryRefusal) as exc:
        print(json.dumps({"error": exc.code}))
        return 1
    except KeyStoreUnavailable:
        print(json.dumps({"error": "keystore_unavailable"}))
        return 1
    except (ValueError, OSError, sqlite3.Error):
        print(json.dumps({"error": "configuration_unavailable"}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
