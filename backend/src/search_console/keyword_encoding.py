from urllib.parse import quote, unquote


KEYWORD_ENCODING_VERSION = "utf8-rfc3986-v1"


def encode_keyword_utf8(keyword_text: str) -> str:
    """Return the canonical URL-encoded UTF-8 value stored with a material keyword."""
    value = str(keyword_text or "").strip()
    if not value:
        raise ValueError("关键词不能为空")
    return quote(value, safe="", encoding="utf-8", errors="strict")


def keyword_encoding_matches(keyword_text: str, encoded_value: str) -> bool:
    if not keyword_text or not encoded_value:
        return False
    try:
        return unquote(encoded_value, encoding="utf-8", errors="strict") == keyword_text
    except (UnicodeDecodeError, ValueError):
        return False
