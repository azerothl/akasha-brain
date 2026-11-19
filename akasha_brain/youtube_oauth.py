"""Client OAuth Google de bureau et transport HTTPS à destinations fixes."""

from base64 import urlsafe_b64encode
from hashlib import sha256
from hmac import compare_digest
from http.client import HTTPSConnection, HTTPException
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import re
from secrets import token_urlsafe
from time import monotonic
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser

from .service_registry import ServiceError


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_HOST = "oauth2.googleapis.com"
ANALYTICS_HOST = "youtubeanalytics.googleapis.com"
SCOPES = ("https://www.googleapis.com/auth/yt-analytics.readonly",
          "https://www.googleapis.com/auth/youtube.readonly")
MAX_RESPONSE = 65536


def client_fields(source):
    if not isinstance(source, dict):
        raise ServiceError("oauth_desktop_client_required")
    identifier, secret = source.get("client_id"), source.get("client_secret", "")
    if (not isinstance(identifier, str) or
            not re.fullmatch(r"[A-Za-z0-9_-]{1,220}\.apps\.googleusercontent\.com", identifier) or
            not isinstance(secret, str) or not re.fullmatch(r"[!-~]{0,256}", secret)):
        raise ServiceError("oauth_desktop_client_required")
    return {"client_id": identifier, **({"client_secret": secret} if secret else {})}


def load_client(path):
    try:
        with path.open("rb") as source:
            raw = source.read(16385)
        config = json.loads(raw) if len(raw) <= 16384 else None
    except (OSError, ValueError, RecursionError):
        raise ServiceError("oauth_desktop_client_required") from None
    return client_fields(config.get("installed") if isinstance(config, dict) else None)


def browser_code(client_id, *, open_browser=webbrowser.open, wait_seconds=180):
    state, verifier = token_urlsafe(32), token_urlsafe(48)
    challenge = urlsafe_b64encode(sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    outcome = []

    class Callback(BaseHTTPRequestHandler):
        def setup(self):
            self.request.settimeout(2)
            super().setup()

        def log_message(self, *_):
            pass

        def do_GET(self):
            status = 400
            message = b"Requete OAuth invalide."
            try:
                target = urlsplit(self.path)
                values = parse_qs(target.query, max_num_fields=16, keep_blank_values=True)
                received_state, = values.get("state", ())
                local = self.headers.get_all("Host") == [address]
                if local and target.path == "/callback" and compare_digest(received_state.encode(), state.encode()):
                    code, = values.get("code", ("",))
                    error, = values.get("error", ("",))
                    if bool(code) != bool(error) and (not code or re.fullmatch(r"[!-~]{1,2048}", code)):
                        outcome.append(code)
                        status = 200
                        message = b"Retournez dans Akasha Brain. Vous pouvez fermer cet onglet."
            except ValueError:
                pass
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    with HTTPServer(("127.0.0.1", 0), Callback) as listener:
        address = f"127.0.0.1:{listener.server_port}"
        redirect = f"http://{address}/callback"
        query = urlencode({"client_id": client_id, "response_type": "code", "redirect_uri": redirect,
                           "scope": " ".join(SCOPES), "state": state, "code_challenge": challenge,
                           "code_challenge_method": "S256", "access_type": "offline", "prompt": "consent"})
        if not open_browser(f"{AUTH_URL}?{query}"):
            raise ServiceError("oauth_browser_unavailable")
        until = monotonic() + wait_seconds
        listener.timeout = 0.25
        while not outcome and monotonic() < until:
            listener.handle_request()
    if not outcome:
        raise ServiceError("oauth_callback_timeout")
    if not outcome[0]:
        raise ServiceError("oauth_consent_denied")
    return outcome[0], redirect, verifier


def https(method, host, path, *, form=None, access=None):
    headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
    body = None
    if form is not None:
        body = urlencode(form).encode("ascii")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if access is not None:
        headers["Authorization"] = f"Bearer {access}"
    connection = HTTPSConnection(host, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers)
        with connection.getresponse() as response:
            content = response.read(MAX_RESPONSE + 1)
            if len(content) > MAX_RESPONSE:
                raise ServiceError("budget_exceeded")
            return response.status, content
    except (OSError, HTTPException):
        raise ServiceError("provider_unavailable") from None
    finally:
        connection.close()


def json_object(raw):
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError):
        raise ServiceError("provider_response_invalid") from None
    if not isinstance(data, dict):
        raise ServiceError("provider_response_invalid")
    return data


def token(fields, *, first=False):
    status, body = https("POST", TOKEN_HOST, "/token", form=fields)
    if status == 429 or status >= 500:
        raise ServiceError("provider_unavailable")
    data = json_object(body)
    if status != 200:
        reason = "oauth_reconnect_required" if data.get("error") == "invalid_grant" else "oauth_token_denied"
        raise ServiceError(reason)
    access, refresh = data.get("access_token"), data.get("refresh_token")
    scopes = data.get("scope")
    token_type = data.get("token_type")
    if (not isinstance(access, str) or not re.fullmatch(r"[A-Za-z0-9._~+/-]{1,2048}=*", access)
            or not isinstance(token_type, str) or token_type.lower() != "bearer"
            or (refresh is not None and (not isinstance(refresh, str) or not re.fullmatch(r"[!-~]{1,1536}", refresh)))):
        raise ServiceError("provider_response_invalid")
    if (first or scopes is not None) and (not isinstance(scopes, str) or set(scopes.split()) != set(SCOPES)):
        raise ServiceError("oauth_scope_denied")
    if first and refresh is None:
        raise ServiceError("oauth_refresh_missing")
    return access, refresh
