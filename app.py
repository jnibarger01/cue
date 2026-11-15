import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qs, urlsplit

from flask import Flask, jsonify, render_template, request
from requests import Session
from requests.exceptions import RequestException
from youtube_transcript_api import (
    AgeRestricted, CouldNotRetrieveTranscript, NoTranscriptFound, RequestBlocked,
    TranscriptsDisabled, VideoUnavailable, VideoUnplayable, YouTubeTranscriptApi,
)

app = Flask(__name__, static_folder="public/static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024
MAX_LINKS = 10
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
EMBEDS = {"youtube-nocookie.com", "www.youtube-nocookie.com"}


def extract_id(url):
    if not url or len(url) > 2048 or any(c.isspace() for c in url):
        return None
    try:
        parts = urlsplit(url)
        if not parts.scheme:
            parts = urlsplit(f"https://{url}")
        if parts.scheme not in {"https", "http"} or parts.netloc.lower() != parts.hostname:
            return None
    except ValueError:
        return None

    host = parts.hostname
    path = parts.path.removeprefix("/").removesuffix("/").split("/")
    candidate = ""
    if host in {"youtu.be", "www.youtu.be"} and len(path) == 1:
        candidate = path[0]
    elif host in YOUTUBE and path == ["watch"]:
        ids = parse_qs(parts.query, keep_blank_values=True).get("v", [])
        candidate = ids[0] if len(ids) == 1 else ""
    elif len(path) == 2:
        kind, value = path
        if (kind == "embed" and host in YOUTUBE | EMBEDS) or (
            host in YOUTUBE and kind in {"shorts", "live"}
        ):
            candidate = value
    return candidate if VIDEO_ID.fullmatch(candidate) else None


class CaptionSession(Session):
    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", (3.05, 6))
        return super().request(method, url, **kwargs)


def lookup(url):
    url = url.strip() if isinstance(url, str) else ""
    video_id = extract_id(url)
    item = {"url": url[:2048], "video_id": video_id}
    if not video_id:
        return {**item, "error": "Enter a valid YouTube video URL."}

    try:
        with CaptionSession() as session:
            tracks = YouTubeTranscriptApi(http_client=session).list(video_id)
            try:
                track = tracks.find_transcript(["en"])
            except NoTranscriptFound:
                track = next(iter(tracks), None)
            if track is not None:
                text = "\n".join(snippet.text for snippet in track.fetch()).strip()
                if text:
                    return {**item, "text": text, "language": track.language}
        error = "No captions were found for this video."
    except TranscriptsDisabled:
        error = "Captions are disabled or unavailable for this video."
    except (VideoUnavailable, VideoUnplayable, AgeRestricted):
        error = "This video may be private, deleted, or restricted."
    except RequestBlocked:
        error = "YouTube blocked this server's requests. Try running Cue locally."
    except (CouldNotRetrieveTranscript, RequestException):
        error = "YouTube could not return captions right now. Try again shortly."
    return {**item, "error": error}


@app.get("/")
def index():
    return render_template("index.html", max_links=MAX_LINKS)


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="The request is too large."), 413


@app.post("/api/transcripts")
def transcripts():
    body = request.get_json(silent=True)
    urls = body.get("urls") if isinstance(body, dict) else None
    if not isinstance(urls, list) or not 1 <= len(urls) <= MAX_LINKS:
        return jsonify(error=f"Send between 1 and {MAX_LINKS} YouTube URLs."), 400

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lookup, urls))
    return jsonify(results=results)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
