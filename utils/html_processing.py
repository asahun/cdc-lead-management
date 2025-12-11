"""
HTML and text processing utilities for phone scripts and content.
"""

import re
from markupsafe import Markup, escape

STYLE_TAG_RE = re.compile(r"<style.*?>.*?</style>", re.S | re.I)
SCRIPT_TAG_RE = re.compile(r"<script.*?>.*?</script>", re.S | re.I)
TAG_RE = re.compile(r"<[^>]+>")
WHITESPACE_RE = re.compile(r"\n\s*\n+", re.S)
HTML_SNIPPET_RE = re.compile(
    r"<\s*(?:!doctype|html|head|body|section|div|article|main|header|footer|p|h[1-6]|ul|ol|li|table|tr|td)\b",
    re.I,
)


def plain_text_to_html(text: str) -> str:
    """Convert plain text to HTML paragraphs."""
    paragraphs = [para.strip() for para in text.split("\n\n") if para.strip()]
    if not paragraphs:
        return str(Markup("<p>No script available.</p>"))
    
    html_parts = []
    for para in paragraphs:
        lines = [line.strip() for line in para.splitlines()]
        escaped_lines = [escape(line) for line in lines if line]
        if escaped_lines:
            html_parts.append(f"<p>{'<br>'.join(escaped_lines)}</p>")
    
    if not html_parts:
        html_parts.append("<p>No script available.</p>")
    
    return str(Markup("".join(html_parts)))


def looks_like_html(text: str) -> bool:
    """Check if text appears to be HTML."""
    snippet = text.strip()
    if not snippet:
        return False

    lower = snippet.lower()
    if lower.startswith("<!doctype") or lower.startswith("<html") or "<body" in lower:
        return True

    return bool(HTML_SNIPPET_RE.search(lower))


def extract_body_fragment(text: str) -> str:
    """Extract body content from HTML."""
    lower = text.lower()
    body_start = lower.find("<body")
    if body_start != -1:
        start_tag_end = text.find(">", body_start)
        body_end = lower.rfind("</body>")
        if start_tag_end != -1 and body_end != -1:
            return text[start_tag_end + 1 : body_end]
    return text


def strip_tags_to_text(html_text: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    stripped = TAG_RE.sub("\n", html_text)
    stripped = WHITESPACE_RE.sub("\n\n", stripped)
    return stripped.strip()


def prepare_script_content(raw_text: str) -> tuple[str, str]:
    """
    Prepare script content for display.
    Returns (html_content, plain_text_content).
    """
    if not raw_text:
        return str(Markup("<p>No script available.</p>")), ""
    
    if looks_like_html(raw_text):
        content = STYLE_TAG_RE.sub("", raw_text)
        content = SCRIPT_TAG_RE.sub("", content)
        content = extract_body_fragment(content).strip()
        if not content:
            return str(Markup("<p>No script available.</p>")), ""
        plain = strip_tags_to_text(content)
        return str(Markup(content)), plain
    
    plain_text = raw_text.strip()
    html_value = plain_text_to_html(plain_text)
    return html_value, plain_text

