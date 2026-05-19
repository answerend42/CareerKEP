"""HTML / wikitext → 纯文本清洗，以及长文本切片。

只用 stdlib：`html.parser` + 正则。设计目标：
- 不引入第三方 HTML/Markdown 库；
- 对维基百科 disambiguation 页这类语义噪声做检测，让上层决定是否丢弃；
- 切片在最近的句号/换行回溯，避免把句子切成两半，影响后续抽取。
"""

from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import List


_BLOCK_TAGS = {
    "p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    "section", "article", "header", "footer", "blockquote", "pre",
}
_SKIP_TAGS = {"script", "style", "noscript", "template"}

_DISAMBIG_PATTERNS = (
    re.compile(r"\bmay refer to\b", re.IGNORECASE),
    re.compile(r"may also refer to", re.IGNORECASE),
    re.compile(r"是一个消歧义"),
    re.compile(r"可以指"),
)


class _PlainTextExtractor(HTMLParser):
    """提取可见文本，遇到块级标签插入换行。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._parts: List[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        return _normalize_whitespace(joined)


def _normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+", " ", text)
    text = re.sub(r" *\n+ *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def html_to_text(html: str) -> str:
    """把 HTML 片段抽成纯文本。"""

    parser = _PlainTextExtractor()
    parser.feed(html)
    parser.close()
    return parser.text()


_WIKI_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_WIKI_REF_RE = re.compile(r"<ref[^>]*?>.*?</ref>", re.DOTALL | re.IGNORECASE)
_WIKI_SELF_REF_RE = re.compile(r"<ref[^/]*?/>", re.IGNORECASE)
_WIKI_FILE_LINK_RE = re.compile(r"\[\[(?:File|Image|文件|图像):[^\[\]]*?\]\]", re.IGNORECASE)
_WIKI_LINK_RE = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]+))?\]\]")
_WIKI_BOLD_ITALIC_RE = re.compile(r"'{2,5}")
_WIKI_HEADING_RE = re.compile(r"^=+\s*(.+?)\s*=+\s*$", re.MULTILINE)
_WIKI_TABLE_RE = re.compile(r"\{\|.*?\|\}", re.DOTALL)
_WIKI_HTML_TAG_RE = re.compile(r"<[^>]+>")


def wikitext_to_text(wikitext: str) -> str:
    """把 MediaWiki wikitext 抽成纯文本。

    简化方案，覆盖 Wikipedia 主流标记。复杂模板会被整体丢弃，
    这是有意为之——模板里很少有人类可读正文，留下反而是噪声。
    """

    text = wikitext
    text = _WIKI_REF_RE.sub("", text)
    text = _WIKI_SELF_REF_RE.sub("", text)
    text = _WIKI_TABLE_RE.sub("", text)
    # 嵌套模板用循环替换（stdlib 正则不支持递归）
    while True:
        new_text = _WIKI_TEMPLATE_RE.sub("", text)
        if new_text == text:
            break
        text = new_text
    text = _WIKI_FILE_LINK_RE.sub("", text)
    text = _WIKI_LINK_RE.sub(lambda m: m.group(2) or m.group(1), text)
    text = _WIKI_BOLD_ITALIC_RE.sub("", text)
    text = _WIKI_HEADING_RE.sub(r"\1", text)
    text = _WIKI_HTML_TAG_RE.sub("", text)
    return _normalize_whitespace(text)


def looks_like_disambiguation(text: str) -> bool:
    """检测维基百科 disambiguation 页的特征。"""

    head = text[:400]
    return any(pattern.search(head) for pattern in _DISAMBIG_PATTERNS)


_SENTENCE_BOUNDARY_RE = re.compile(r"(?<=[。.!?！？\n])")


def split_long(text: str, max_chars: int, overlap: int = 0) -> List[str]:
    """按句子边界回溯切片，不切坏句子。

    `overlap` 用于让前后片段保留少量重叠上下文，提升 mention 抽取召回。
    """

    if max_chars <= 0:
        raise ValueError("max_chars 必须 > 0")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap 必须满足 0 <= overlap < max_chars")
    if len(text) <= max_chars:
        return [text] if text.strip() else []

    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        if end < n:
            # 在 [start, end] 内回溯找最近的句子边界
            window = text[start:end]
            boundaries = list(_SENTENCE_BOUNDARY_RE.finditer(window))
            if boundaries:
                # 用最后一个边界作为切点，避免切坏句子
                cut_offset = boundaries[-1].end()
                end = start + cut_offset
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= n:
            break
        start = max(end - overlap, end if overlap == 0 else 0)
        if start >= n:
            break
    return chunks
