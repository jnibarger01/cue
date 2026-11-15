"""Cue's Vercel-hosted, single-user web application."""

import os
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from urllib.parse import urlsplit

import requests
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from requests.exceptions import RequestException

from security import constant_time_equal, verify_password
from transcripts import MAX_LINKS

app = Flask(__name__, static_folder="public/static", static_url_path="/static")
app.config.update(
    SECRET_KEY=os.environ.get("CUE_SESSION_SECRET"),
    MAX_CONTENT_LENGTH=32 * 1024,
    SESSION_COOKIE_NAME="cue_session",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=os.environ.get("CUE_COOKIE_SECURE", "true").lower() not in {"0", "false", "no"},
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

_LOGIN_WINDOW_SECONDS = 15 * 60
_LOGIN_MAX_FAILURES = 5
_login_attempts = defaultdict(deque)


def auth_is_configured():
    username = os.environ.get("CUE_USERNAME", "").strip()
    password_hash = os.environ.get("CUE_PASSWORD_HASH", "").strip()
    session_secret = os.environ.get("CUE_SESSION_SECRET", "")
    return bool(username and password_hash and len(session_secret) >= 32)


def _csrf_token():
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def _login_attempt_key():
    return request.remote_addr or "unknown"


def _login_is_limited():
    now = time.monotonic()
    attempts = _login_attempts[_login_attempt_key()]
    while attempts and now - attempts[0] >= _LOGIN_WINDOW_SECONDS:
        attempts.popleft()
    return len(attempts) >= _LOGIN_MAX_FAILURES


def _record_login_failure():
    attempts = _login_attempts[_login_attempt_key()]
    attempts.append(time.monotonic())
    if len(_login_attempts) > 2048:
        now = time.monotonic()
        for address in list(_login_attempts):
            recent = _login_attempts[address]
            while recent and now - recent[0] >= _LOGIN_WINDOW_SECONDS:
                recent.popleft()
            if not recent:
                _login_attempts.pop(address, None)


def _setup_required():
    if request.path.startswith("/api/"):
        return jsonify(error="Cue authentication is not configured. Set the required server environment variables."), 503
    return render_template("setup_required.html"), 503


@app.before_request
def require_single_user_login():
    if request.endpoint in {"static", "login"}:
        return None
    if not auth_is_configured():
        return _setup_required()
    if not session.get("authenticated"):
        if request.path.startswith("/api/"):
            return jsonify(error="Authentication required."), 401
        return redirect(url_for("login"))
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        supplied = request.headers.get("X-CSRF-Token", "")
        if request.endpoint == "logout":
            supplied = request.form.get("csrf_token", "")
        if not constant_time_equal(session.get("csrf_token", ""), supplied):
            if request.path.startswith("/api/"):
                return jsonify(error="Invalid CSRF token."), 400
            return "Invalid CSRF token.", 400
    return None


@app.after_request
def add_security_headers(response):
    if request.endpoint != "static":
        response.headers.setdefault("Cache-Control", "no-store")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
        "form-action 'self'; base-uri 'self'; frame-ancestors 'none'",
    )
    return response


@app.route("/login", methods=["GET", "POST"])
def login():
    if not auth_is_configured():
        return render_template("setup_required.html"), 503
    if request.method == "GET":
        if session.get("authenticated"):
            return redirect(url_for("index"))
        return render_template("login.html", csrf_token=_csrf_token(), error=None)

    if not constant_time_equal(session.get("csrf_token", ""), request.form.get("csrf_token", "")):
        return render_template("login.html", csrf_token=_csrf_token(), error="Your sign-in form expired. Refresh and try again."), 400
    if _login_is_limited():
        response = render_template("login.html", csrf_token=_csrf_token(), error="Too many failed attempts. Wait 15 minutes and try again.")
        return response, 429

    username_ok = constant_time_equal(os.environ.get("CUE_USERNAME", ""), request.form.get("username", ""))
    password_ok = verify_password(
        request.form.get("password", ""),
        os.environ.get("CUE_PASSWORD_HASH", ""),
    )
    if not (username_ok and password_ok):
        _record_login_failure()
        return render_template("login.html", csrf_token=_csrf_token(), error="Invalid username or password."), 401

    _login_attempts.pop(_login_attempt_key(), None)
    session.clear()
    session["authenticated"] = True
    session["csrf_token"] = secrets.token_urlsafe(32)
    session.permanent = True
    return redirect(url_for("index"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
def index():
    return render_template("index.html", max_links=MAX_LINKS, csrf_token=_csrf_token())


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="The request is too large."), 413


@app.post("/api/transcripts")
def transcripts():
    body = request.get_json(silent=True)
    urls = body.get("urls") if isinstance(body, dict) else None
    if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_LINKS:
        return jsonify(error=f"Send between 1 and {MAX_LINKS} YouTube URLs."), 400
    if any(not isinstance(url, str) or len(url) > 2048 for url in urls):
        return jsonify(error="Each item must be a YouTube URL no longer than 2048 characters."), 400

    worker_url = os.environ.get("CUE_WORKER_URL", "").strip().rstrip("/")
    worker_token = os.environ.get("CUE_WORKER_TOKEN", "")
    if not worker_url or len(worker_token) < 32:
        return jsonify(error="The private transcript worker is not configured with a strong service token."), 503

    parsed_worker_url = urlsplit(worker_url)
    allow_http = os.environ.get("CUE_WORKER_ALLOW_HTTP", "").lower() == "true"
    local_http = parsed_worker_url.scheme == "http" and parsed_worker_url.hostname in {"127.0.0.1", "localhost"}
    if (
        not parsed_worker_url.netloc
        or parsed_worker_url.username
        or parsed_worker_url.password
        or parsed_worker_url.query
        or parsed_worker_url.fragment
        or not (parsed_worker_url.scheme == "https" or (allow_http and local_http))
    ):
        return jsonify(error="The private transcript worker URL must use HTTPS."), 503

    headers = {"Authorization": f"Bearer {worker_token}"}
    access_client_id = os.environ.get("CUE_WORKER_ACCESS_CLIENT_ID", "")
    access_client_secret = os.environ.get("CUE_WORKER_ACCESS_CLIENT_SECRET", "")
    if access_client_id and access_client_secret:
        headers["CF-Access-Client-Id"] = access_client_id
        headers["CF-Access-Client-Secret"] = access_client_secret

    try:
        upstream = requests.post(
            worker_url,
            json={"urls": urls},
            headers=headers,
            timeout=(5, 55),
            allow_redirects=False,
        )
    except RequestException:
        return jsonify(error="The private transcript worker is offline or unreachable."), 503

    if upstream.status_code == 429:
        return jsonify(error="The transcript worker is busy. Try again shortly."), 429
    if upstream.status_code != 200:
        return jsonify(error="The transcript worker rejected the request or returned an error."), 502
    try:
        payload = upstream.json()
    except ValueError:
        return jsonify(error="The transcript worker returned an invalid response."), 502
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return jsonify(error="The transcript worker returned an invalid response."), 502
    return jsonify(results=payload["results"])


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
