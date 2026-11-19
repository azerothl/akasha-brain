"""Rapport YouTube de 28 jours lié à une session Akasha."""

from datetime import date, timedelta, timezone
import json
import re
from time import monotonic
from urllib.parse import urlencode
from uuid import UUID, uuid4

from . import project_audit, youtube_oauth as oauth
from .memory_store import MemoryRefusal, connect, stamp
from .service_registry import ServiceError
from .vault_windows import SecretMissing


SERVICE = "youtube-analytics"
REPORT_PATH = "/v2/reports"
CHANNEL_ID = re.compile(r"UC[A-Za-z0-9_-]{22}")
METRICS = ("views", "estimatedMinutesWatched")
# 08:00 UTC garantit que la veille du calendrier YouTube est terminée en heure du Pacifique.
PACIFIC_STANDARD = timezone(timedelta(hours=-8))


def report_path(channel, start, end):
    query = urlencode({"ids": f"channel=={channel}", "startDate": start.isoformat(), "endDate": end.isoformat(),
                       "metrics": ",".join(METRICS), "dimensions": "day", "sort": "day"})
    return f"{REPORT_PATH}?{query}"


def report_data(payload, start, end):
    try:
        columns = [column["name"] for column in payload["columnHeaders"]]
        if sorted(columns) != sorted(("day", *METRICS)):
            raise ValueError
        rows = payload.get("rows", [])
        if not isinstance(rows, list) or len(rows) > 28:
            raise ValueError
        days = {}
        for row in rows:
            if not isinstance(row, list):
                raise ValueError
            values = dict(zip(columns, row, strict=True))
            day = date.fromisoformat(values["day"])
            views, minutes = (values[name] for name in METRICS)
            if (values["day"] != day.isoformat() or not start <= day <= end or day in days or
                    any(type(metric) is not int or not 0 <= metric < 2**63 for metric in (views, minutes))):
                raise ValueError
            days[day] = (views, minutes)
    except (KeyError, TypeError, ValueError):
        raise ServiceError("output_schema") from None
    series = [{"day": day.isoformat(), "views": values[0], "watch_minutes": values[1]}
              for day, values in sorted(days.items())]
    return {"requested_start": start.isoformat(), "requested_end": end.isoformat(),
            "first_returned_day": min(days).isoformat() if days else None,
            "last_returned_day": max(days).isoformat() if days else None,
            "days_returned": len(days), "coverage": "complete" if len(days) == 28 else "partial" if days else "empty",
            "views": sum(day["views"] for day in series) if series else None,
            "watch_minutes": sum(day["watch_minutes"] for day in series) if series else None,
            "daily": series}


class YouTubeAnalytics:
    def __init__(self, vault):
        self.vault = vault
        self.clock = vault.sessions.clock
        self.path = vault.path.with_name("youtube-analytics.sqlite")
        if self.path.resolve() != self.path:
            raise ServiceError("storage_invalid")
        with connect(self.path, create=True) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS youtube_connections (
                id TEXT PRIMARY KEY, session TEXT NOT NULL, channel TEXT NOT NULL, handle TEXT,
                revoked INTEGER NOT NULL DEFAULT 0, google_revoked INTEGER NOT NULL DEFAULT 0
            )""")

    def row(self, db, session, grant):
        self.vault.require_session(session)
        row = db.execute("SELECT * FROM youtube_connections WHERE session = ? AND id = ?",
                         (str(session), str(grant))).fetchone()
        if row is None:
            raise ServiceError("connection_unavailable")
        return row

    def audit(self, operation, decision):
        project_audit.record(self.path, action=f"youtube.{operation}", risk="R3", actor="operator",
                             decision=decision)

    def approve(self, operation, approve, preview):
        until = monotonic() + 300
        if approve({"service": SERVICE, "operation": operation, **preview}) is not True:
            self.audit(operation, "denied")
            raise ServiceError("egress_approval_required")
        self.audit(operation, "approved")
        return until

    @staticmethod
    def fresh(until):
        if monotonic() >= until:
            raise ServiceError("approval_expired")

    def connect_account(self, session, channel, client_path, approve):
        if not CHANNEL_ID.fullmatch(channel):
            raise ServiceError("youtube_channel_invalid")
        self.vault.require_session(session)
        self.vault.keystore()
        client = oauth.load_client(client_path)
        end = self.last_completed_day()
        start = end - timedelta(days=27)
        destination = f"https://{oauth.ANALYTICS_HOST}{report_path(channel, start, end)}"
        until = self.approve("connect", approve, {"channel": channel, "authorization": oauth.AUTH_URL,
                                                  "token_endpoint": f"https://{oauth.TOKEN_HOST}/token",
                                                  "channel_check": destination,
                                                  "scopes": list(oauth.SCOPES)})
        self.fresh(until)
        code, redirect, verifier = oauth.browser_code(client["client_id"])
        self.fresh(until)
        access, refresh = oauth.token({**client, "code": code, "redirect_uri": redirect,
                                       "grant_type": "authorization_code", "code_verifier": verifier}, first=True)
        # Google vérifie le droit de l’utilisateur sur la chaîne visée par la requête exacte.
        self.fresh(until)
        self.query(channel, start, end, access)
        handle = self.seal(session, client, refresh)
        grant = uuid4()
        try:
            with connect(self.path) as db:
                db.execute("INSERT INTO youtube_connections (id, session, channel, handle) VALUES (?, ?, ?, ?)",
                           (str(grant), str(session), channel, str(handle)))
        except Exception:
            self.vault.erase(session, handle)
            raise
        return self.status(session, grant)

    def seal(self, session, client, refresh):
        secret = bytearray(json.dumps({**client, "refresh_token": refresh}, separators=(",", ":")), "ascii")
        return self.vault.seal(session, secret)

    def credential(self, session, handle):
        try:
            with self.vault.resolve(session, UUID(handle), approve=lambda: True) as secret:
                return oauth.json_object(bytes(secret))
        except (MemoryRefusal, SecretMissing):
            raise ServiceError("credential_unavailable") from None

    def status(self, session, grant):
        with connect(self.path) as db:
            row = self.row(db, session, grant)
        state = "connected"
        if row["revoked"]:
            state = "revoked" if row["google_revoked"] and not row["handle"] else "revocation_pending"
        elif UUID(row["handle"]) not in self.vault.handles(session):
            state = "credential_unavailable"
        return {"connection": str(grant), "service": SERVICE, "channel": row["channel"],
                "state": state, "google_revoked": bool(row["google_revoked"])}

    def last_completed_day(self):
        return self.clock().astimezone(PACIFIC_STANDARD).date() - timedelta(days=1)

    def report(self, session, grant, end, approve):
        latest = self.last_completed_day()
        end = latest if end is None else end
        if end > latest or end < date(2005, 2, 14):
            raise ServiceError("report_dates_invalid")
        start = end - timedelta(days=27)
        with connect(self.path) as db:
            row = self.live(db, session, grant)
        channel = row["channel"]
        path = report_path(channel, start, end)
        destination = f"https://{oauth.ANALYTICS_HOST}{path}"
        until = self.approve("report", approve, {"channel": channel, "destination": destination,
                                                 "token_endpoint": f"https://{oauth.TOKEN_HOST}/token"})
        previous = replacement = None
        try:
            with connect(self.path) as db:
                row = self.live(db, session, grant)
                self.fresh(until)
                credential = self.credential(session, row["handle"])
                access, rotated = oauth.token({**credential, "grant_type": "refresh_token"})
                if rotated and rotated != credential["refresh_token"]:
                    previous = UUID(row["handle"])
                    replacement = self.seal(session, oauth.client_fields(credential), rotated)
                    db.execute("UPDATE youtube_connections SET handle = ? WHERE id = ?", (str(replacement), str(grant)))
        except Exception:
            if replacement is not None:
                self.vault.erase(session, replacement)
            raise
        if previous is not None:
            self.vault.erase(session, previous)
        with connect(self.path) as db:
            self.live(db, session, grant)
            self.fresh(until)
            result = self.query(channel, start, end, access)
        return {"result": result, "provenance": {"source": "external", "service": SERVICE, "channel": channel,
                                                "destination": destination, "observed_at": stamp(self.clock())}}

    def live(self, db, session, grant):
        row = self.row(db, session, grant)
        if row["revoked"]:
            raise ServiceError("connection_revoked")
        return row

    @staticmethod
    def query(channel, start, end, access):
        status, raw = oauth.https("GET", oauth.ANALYTICS_HOST, report_path(channel, start, end), access=access)
        if status != 200:
            code = {401: "oauth_reconnect_required", 403: "youtube_channel_or_api_denied", 404: "youtube_channel_or_api_denied"}
            raise ServiceError(code.get(status, "provider_unavailable"))
        return report_data(oauth.json_object(raw), start, end)

    def revoke(self, session, grant, approve):
        with connect(self.path) as db:
            row = self.row(db, session, grant)
        until = None
        if not row["google_revoked"]:
            until = self.approve("revoke", approve, {"channel": row["channel"],
                                 "destination": f"https://{oauth.TOKEN_HOST}/revoke",
                                 "effect": "Révoquer le consentement Google de ce projet OAuth."})
            self.fresh(until)
        with connect(self.path) as db:
            self.row(db, session, grant)
            db.execute("UPDATE youtube_connections SET revoked = 1 WHERE id = ?", (str(grant),))
        with connect(self.path) as db:
            row = self.row(db, session, grant)
            if not row["google_revoked"]:
                self.fresh(until)
                credential = self.credential(session, row["handle"])
                status, _ = oauth.https("POST", oauth.TOKEN_HOST, "/revoke", form={"token": credential["refresh_token"]})
                if status != 200:
                    raise ServiceError("google_revocation_unconfirmed")
                db.execute("UPDATE youtube_connections SET google_revoked = 1 WHERE id = ?", (str(grant),))
        with connect(self.path) as db:
            row = self.row(db, session, grant)
            if row["handle"]:
                handle = UUID(row["handle"])
                if handle in self.vault.handles(session):
                    self.vault.erase(session, handle)
                db.execute("UPDATE youtube_connections SET handle = NULL WHERE id = ?", (str(grant),))
        return self.status(session, grant)
