from base64 import urlsafe_b64encode
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import sys
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen
from uuid import UUID

import pytest

from akasha_brain import service_cli, youtube_oauth as oauth
from akasha_brain.conversation_sessions import SessionStore
from akasha_brain.conversation_vault import SessionVault
from akasha_brain.service_registry import ServiceError
from akasha_brain.vault_windows import SecretMissing, WindowsKeyStore
from akasha_brain.youtube_analytics import METRICS, YouTubeAnalytics, report_data


CHANNEL = "UC" + "x" * 22
CLIENT = "fixture.apps.googleusercontent.com"
CLIENT_SECRET = "g12-synthetic-client-secret"
REFRESH = "g12-synthetic-refresh-token"
ROTATED = "g12-synthetic-rotated-refresh-token"
ACCESS = "g12-synthetic-access-token"
END = date(2026, 11, 18)
START = END - timedelta(days=27)
COLUMNS = [{"name": name} for name in ("day", *METRICS)]


def payload(rows):
    return {"columnHeaders": COLUMNS, "rows": rows}


def test_desktop_oauth_pkce_and_callback(monkeypatch):
    query_seen = {}

    def open_browser(url):
        parsed = urlsplit(url)
        query = parse_qs(parsed.query)
        query_seen.update(query)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == oauth.AUTH_URL
        assert query["scope"] == [" ".join(oauth.SCOPES)]
        assert query["access_type"] == ["offline"]

        def redirect():
            target = query["redirect_uri"][0]
            assert urlsplit(target).hostname == "127.0.0.1"
            with pytest.raises(HTTPError) as rejected:
                urlopen(target + "?state=wrong&code=ignored", timeout=4)
            assert rejected.value.code == 400
            with urlopen(target + "?" + urlencode({"state": query["state"][0], "code": "returned-code"}),
                         timeout=4) as response:
                assert response.headers["Cache-Control"] == "no-store"
                assert b"returned-code" not in response.read()

        callback.append(pool.submit(redirect))
        return True

    callback = []
    with ThreadPoolExecutor(max_workers=1) as pool:
        code, redirect, verifier = oauth.browser_code(CLIENT, open_browser=open_browser, wait_seconds=5)
        callback[0].result()
    assert code == "returned-code" and redirect == query_seen["redirect_uri"][0]
    assert query_seen["code_challenge_method"] == ["S256"]
    assert query_seen["code_challenge"] == [urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")]


@pytest.mark.parametrize("rows", [
    [["2026-11-19", 1, 2]], [["2026-11-18", True, 2]], [["2026-11-18", 1, -1]],
    [["2026-11-18", 1, 2], ["2026-11-18", 1, 2]], [["2026-11-18", 1]],
])
def test_report_refuses_invalid_daily_rows(rows):
    with pytest.raises(ServiceError, match="output_schema"):
        report_data(payload(rows), START, END)


def test_empty_or_partial_days_stay_explicit():
    empty = report_data({"columnHeaders": COLUMNS}, START, END)
    assert (empty["views"], empty["watch_minutes"], empty["coverage"]) == (None, None, "empty")
    partial = report_data(payload([[START.isoformat(), 10, 21], ["2026-11-17", 4, 9]]), START, END)
    assert (partial["views"], partial["watch_minutes"], partial["coverage"]) == (14, 30, "partial")
    assert partial["days_returned"] == 2 and partial["last_returned_day"] == "2026-11-17"


def test_token_exchange_refuses_excess_scope(monkeypatch):
    def response(*args, **kwargs):
        return 200, json.dumps({"access_token": ACCESS, "refresh_token": REFRESH, "token_type": "Bearer",
                                 "scope": " ".join((*oauth.SCOPES, "https://www.googleapis.com/auth/youtube"))})
    monkeypatch.setattr(oauth, "https", response)
    with pytest.raises(ServiceError, match="oauth_scope_denied"):
        oauth.token({}, first=True)


@pytest.mark.skipif(sys.platform != "win32", reason="Nécessite le Gestionnaire d’identification Windows")
def test_cli_report_and_revocation_with_windows_vault(tmp_path, monkeypatch, capsys):
    client = tmp_path / "client.json"
    client.write_text(json.dumps({"installed": {"client_id": CLIENT, "client_secret": CLIENT_SECRET,
                                                "token_uri": "https://ignored.invalid"}}), encoding="utf8")
    transcript, approvals = [], []
    google_online = True
    active = True
    session_dir = tmp_path / "akasha"
    sessions = SessionStore(session_dir / "conversation-sessions.sqlite",
                            clock=lambda: datetime(2026, 11, 19, 14, tzinfo=timezone.utc))
    vault = SessionVault(session_dir, sessions)
    session, other = sessions.create(), sessions.create()
    handles = set()
    monkeypatch.setattr(service_cli, "SessionStore", lambda _: sessions)
    monkeypatch.setattr(oauth, "browser_code", lambda _: ("code", "http://127.0.0.1:17850/callback", "verifier"))
    monkeypatch.setattr(service_cli, "egress", lambda preview: approvals.append(preview) or True)

    def google(method, host, path, *, form=None, access=None):
        nonlocal active
        transcript.append((method, host, urlsplit(path).path))
        if (method, host, path) == ("POST", oauth.TOKEN_HOST, "/token"):
            assert active and form["client_secret"] == CLIENT_SECRET
            reply = {"access_token": ACCESS, "token_type": "Bearer", "scope": " ".join(oauth.SCOPES)}
            if form["grant_type"] == "authorization_code":
                assert form["code_verifier"] == "verifier"
                reply["refresh_token"] = REFRESH
            else:
                assert form["refresh_token"] == REFRESH
                reply["refresh_token"] = ROTATED
            return 200, json.dumps(reply).encode()
        if (method, host, path) == ("POST", oauth.TOKEN_HOST, "/revoke"):
            assert form == {"token": ROTATED} and access is None
            if not google_online:
                return 503, b""
            active = False
            return 200, b""
        assert (method, host, urlsplit(path).path) == ("GET", oauth.ANALYTICS_HOST, "/v2/reports")
        assert active and access == ACCESS and form is None
        query = parse_qs(urlsplit(path).query)
        assert query == {"ids": [f"channel=={CHANNEL}"], "startDate": [START.isoformat()],
                         "endDate": [END.isoformat()], "metrics": [",".join(METRICS)],
                         "dimensions": ["day"], "sort": ["day"]}
        data = [[(START + timedelta(days=i)).isoformat(), i + 1, 2 * (i + 1)] for i in range(28)]
        return 200, json.dumps(payload(data)).encode()

    def cli(*args, error=None, owner=session):
        monkeypatch.setattr(sys, "argv", ["service_cli", "--directory", str(session_dir), "youtube", args[0],
                                         "--session", str(owner), *map(str, args[1:])])
        assert service_cli.main() == int(error is not None)
        output = capsys.readouterr()
        assert all(secret not in output.out + output.err for secret in (CLIENT_SECRET, REFRESH, ROTATED, ACCESS))
        result = json.loads(output.out)
        if error:
            assert result == {"error": error}
        return result

    monkeypatch.setattr(oauth, "https", google)
    try:
        connected = cli("connect", "--client", client, "--channel", CHANNEL)
        assert connected["state"] == "connected"
        reference = ["--connection", UUID(connected["connection"])]
        old, = vault.handles(session)
        handles.add(old)
        sealed = WindowsKeyStore().get(old)
        try:
            assert json.loads(sealed)["refresh_token"] == REFRESH and ACCESS.encode() not in sealed
        finally:
            sealed[:] = bytes(len(sealed))

        before = len(transcript)
        cli("report", *reference, owner=other, error="connection_unavailable")
        cli("revoke", *reference, owner=other, error="connection_unavailable")
        with monkeypatch.context() as denied:
            denied.setattr(service_cli, "egress", lambda _: False)
            cli("report", *reference, error="egress_approval_required")
        assert len(transcript) == before
        outcome = cli("report", *reference)
        assert outcome["provenance"]["channel"] == CHANNEL
        assert outcome["result"]["coverage"] == "complete"
        assert (outcome["result"]["views"], outcome["result"]["watch_minutes"]) == (406, 812)
        new, = vault.handles(session)
        handles.add(new)
        assert new != old
        with pytest.raises(SecretMissing):
            WindowsKeyStore().get(old)

        google_online = False
        cli("revoke", *reference, error="google_revocation_unconfirmed")
        assert cli("status", *reference)["state"] == "revocation_pending"
        before = len(transcript)
        cli("report", *reference, error="connection_revoked")
        assert len(transcript) == before
        google_online = True
        revoked = cli("revoke", *reference)
        assert revoked["state"] == "revoked" and revoked["google_revoked"] and not active
        before = len(transcript)
        assert cli("revoke", *reference) == revoked
        cli("report", *reference, error="connection_revoked")
        assert len(transcript) == before and vault.handles(session) == ()
        with pytest.raises(SecretMissing):
            WindowsKeyStore().get(new)
        assert all(value not in json.dumps(approvals) for value in (CLIENT_SECRET, REFRESH, ROTATED, ACCESS))
        for file in session_dir.iterdir():
            assert all(value.encode() not in file.read_bytes() for value in (CLIENT_SECRET, REFRESH, ROTATED, ACCESS))
    finally:
        for handle in set(vault.handles(session)) | handles:
            WindowsKeyStore().erase(handle)
