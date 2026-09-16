from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit


@dataclass(frozen=True)
class AttributionCandidate:
    account_id: int
    user_id: str | None
    keyword_id: str | None
    normalized_url: str


def normalize_url(value: str) -> str:
    parts = urlsplit(unquote(value.strip()))
    host = (parts.hostname or "").lower()
    port = f":{parts.port}" if parts.port and parts.port not in {80, 443} else ""
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), f"{host}{port}", path, parts.query, ""))


def extract_tracking_keys(value: str) -> tuple[str | None, str | None]:
    query = parse_qs(urlsplit(unquote(value)).query)
    user_id = (query.get("userid") or query.get("user_id") or [None])[0]
    keyword_id = (query.get("keywordid") or query.get("keyword_id") or [None])[0]
    return user_id, keyword_id


def attribute_uniquely(event_url: str, candidates: list[AttributionCandidate]) -> AttributionCandidate | None:
    event_user, event_keyword = extract_tracking_keys(event_url)
    normalized_event = normalize_url(event_url)
    exact = [candidate for candidate in candidates if event_user and event_keyword and candidate.user_id == event_user and candidate.keyword_id == event_keyword]
    if len(exact) == 1:
        return exact[0]
    url_matches = [candidate for candidate in candidates if normalize_url(candidate.normalized_url).split("?", 1)[0] == normalized_event.split("?", 1)[0]]
    return url_matches[0] if len(url_matches) == 1 else None

