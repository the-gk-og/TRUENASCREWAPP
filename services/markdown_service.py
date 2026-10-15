"""
services/markdown_service.py
============================
Markdown -> sanitised HTML.

Everything a user types into a description / note is rendered through
``render_markdown`` so the output is always safe to inject with ``|safe``
(or ``innerHTML``).  Raw HTML typed by users is stripped, not escaped,
and only a small allow-list of tags is kept.
"""

import re

import markdown as _markdown
import nh3
from markupsafe import Markup

_EXTENSIONS = ["fenced_code", "tables", "sane_lists", "nl2br"]

_ALLOWED_TAGS = {
    "p", "br", "hr", "strong", "b", "em", "i", "u", "s", "del", "code", "pre",
    "blockquote", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6",
    "a", "table", "thead", "tbody", "tr", "th", "td", "span",
}

_ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "th": {"align"},
    "td": {"align"},
}


_LIST_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")


def _prepare(text: str) -> str:
    """
    Python-Markdown needs a blank line before a list; people (and phones)
    rarely type one.  Insert it so "Bring:\n- cables\n- tape" just works.
    Lines inside fenced code blocks are left alone.
    """
    out: list[str] = []
    in_fence = False
    prev = ""
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip().startswith("```"):
            in_fence = not in_fence
        elif (not in_fence and _LIST_RE.match(line)
              and prev.strip() and not _LIST_RE.match(prev)
              and not prev.startswith((" ", "\t"))):
            out.append("")
        out.append(line)
        prev = line
    return "\n".join(out)


def render_markdown(text: str | None) -> Markup:
    """Render *text* as sanitised HTML.  Returns '' for empty input."""
    if not text or not str(text).strip():
        return Markup("")
    html = _markdown.markdown(_prepare(str(text)), extensions=_EXTENSIONS, output_format="html")
    clean = nh3.clean(
        html,
        tags=_ALLOWED_TAGS,
        attributes=_ALLOWED_ATTRIBUTES,
        url_schemes={"http", "https", "mailto", "tel"},
        link_rel="noopener noreferrer",
        set_tag_attribute_values={"a": {"target": "_blank"}},
        allowed_classes={"code": {f"language-{l}" for l in (
            "python", "js", "javascript", "json", "bash", "sh", "html", "css", "text")}},
    )
    return Markup(clean)
