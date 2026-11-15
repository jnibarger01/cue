"""YouTube transcript retrieval, intended to run on the owner's workstation."""

import os
import re
from urllib.parse import parse_qs, urlsplit

from requests import Session
from requests.exceptions import RequestException
from youtube_transcript_api import (
    AgeRestricted,
    CouldNotRetrieveTranscript,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    VideoUnplayable,
    YouTubeTranscriptApi,
)
from youtube_transcript_api.proxies import GenericProxyConfig

MAX_LINKS = 10
VIDEO_ID = re.compile(r"[A-Za-z0-9_-]{11}")
YOUTUBE = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
EMBEDS = {"youtube-nocookie.com", "www.youtube-nocookie.com"}


def extract_id(url):
    if not isinstance(url, str) or not url or len(url) > 2048 or any(c.isspace() for c in url):
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
            proxy_url = os.environ.get("YOUTUBE_PROXY_URL")
            proxy = GenericProxyConfig(https_url=proxy_url) if proxy_url else None
            tracks = YouTubeTranscriptApi(http_client=session, proxy_config=proxy).list(video_id)
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
        error = "YouTube blocked this connection. Try again later or configure a proxy on the worker."
    except (CouldNotRetrieveTranscript, RequestException):
        error = "YouTube could not return captions right now. Try again shortly."
    return {**item, "error": error}
