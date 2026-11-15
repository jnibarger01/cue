"""Narrow, token-protected transcript worker for the owner's workstation."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, jsonify, request

from security import constant_time_equal
from transcripts import MAX_LINKS, lookup

app = Flask("cue_worker")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024
_active_jobs = threading.BoundedSemaphore(value=2)


def _authorized():
    expected = os.environ.get("CUE_WORKER_TOKEN", "")
    authorization = request.headers.get("Authorization", "")
    scheme, separator, provided = authorization.partition(" ")
    return bool(separator) and scheme.lower() == "bearer" and constant_time_equal(expected, provided)


@app.get("/healthz")
def health():
    return jsonify(status="ok")


@app.post("/")
@app.post("/api/transcripts")
@app.post("/cue-worker")
@app.post("/cue-worker/api/transcripts")
def transcripts():
    if len(os.environ.get("CUE_WORKER_TOKEN", "")) < 32:
        return jsonify(error="Worker service authentication is not configured with a strong token."), 503
    if not _authorized():
        return jsonify(error="Unauthorized."), 401

    body = request.get_json(silent=True)
    urls = body.get("urls") if isinstance(body, dict) else None
    if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_LINKS:
        return jsonify(error=f"Send between 1 and {MAX_LINKS} YouTube URLs."), 400
    if any(not isinstance(url, str) or len(url) > 2048 for url in urls):
        return jsonify(error="Each item must be a YouTube URL no longer than 2048 characters."), 400

    if not _active_jobs.acquire(blocking=False):
        return jsonify(error="Worker is busy. Try again shortly."), 429
    try:
        with ThreadPoolExecutor(max_workers=min(5, len(urls))) as pool:
            results = list(pool.map(lookup, urls))
        return jsonify(results=results)
    finally:
        _active_jobs.release()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("CUE_WORKER_PORT", "8787")))
