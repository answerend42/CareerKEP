"""Token 过滤：区分「README 高频词」与「像 evidence 的技术词」。"""

from __future__ import annotations

import re

# README / 自然语言高频词（非技术实体）
_EVIDENCE_STOPWORDS = frozenset({
    "the", "and", "for", "with", "from", "this", "that", "you", "your", "our", "their", "they",
    "are", "was", "were", "has", "have", "had", "but", "not", "any", "all", "one", "two", "three",
    "use", "using", "used", "make", "makes", "made", "new", "old", "also", "just", "like",
    "into", "onto", "over", "more", "less", "most", "some", "each", "very", "much", "many",
    "such", "than", "then", "there", "here", "when", "where", "what", "which", "while",
    "can", "could", "would", "should", "will", "shall", "may", "might", "must", "does", "did",
    "how", "why", "who", "whom", "whose", "about", "after", "before", "between", "under",
    "code", "data", "file", "files", "line", "lines", "work", "works", "time", "times",
    "list", "item", "items", "case", "cases", "need", "needs", "want", "wants", "help",
    "see", "seen", "look", "looks", "find", "found", "know", "knows", "known", "get", "got",
    "way", "ways", "let", "lets", "run", "runs", "ran", "open", "close", "read", "reads",
    "write", "writes", "add", "adds", "build", "built", "support", "supports", "supported",
    "first", "second", "next", "last", "other", "another", "same", "since", "only", "even",
    "page", "section", "example", "examples", "article", "articles", "book", "books",
    "important", "key", "main", "general", "specific", "common", "standard", "best", "good",
    "name", "names", "user", "users", "level", "levels", "type", "types", "value", "values",
    "version", "versions", "release", "releases", "change", "changes", "update", "updates",
    "github", "gitlab", "license", "copyright", "readme", "contributing", "docs", "doc",
    "project", "projects", "repo", "repository", "repositories", "demo", "demos", "sample",
    "system", "systems", "platform", "platforms", "service", "services", "model", "models",
    "https", "http", "www", "com", "org", "net", "io", "co", "cn", "pdf", "html", "blob",
    "master", "main", "tree", "wiki", "link", "links", "url", "urls", "href", "src", "alt",
    "description", "title", "summary", "content", "abstract", "intro", "introduction",
    "guide", "tutorial", "tutorials", "course", "courses", "video", "videos", "blog", "blogs",
    "website", "started", "start", "create", "created", "check", "default", "allow", "easy",
    "many", "each", "some", "application", "computer", "language", "libraries", "library",
    "request", "client", "server", "features", "feature", "additional", "latest", "based",
    "documentation", "examples", "source", "free", "open", "tools", "tool",
    "google", "apple", "microsoft", "amazon", "facebook", "twitter",
    "these", "issues", "different", "applications", "learn", "multiple",
    "security", "provides", "their", "them", "they", "those", "through",
})

_CAMEL_CASE = re.compile(r"^[A-Z][a-z]+|[a-z]+[A-Z]")


def looks_like_evidence_token(token: str) -> bool:
    """nodes_auto 用：排除自然语言高频词，保留像库/框架/协议名的 token。"""

    low = token.lower()
    if low in _EVIDENCE_STOPWORDS:
        return False
    if len(low) < 3:
        return False
    # 数字、点号后缀、CamelCase → 技术名信号
    if any(ch.isdigit() for ch in token):
        return True
    if "." in token:
        return True
    if _CAMEL_CASE.search(token):
        return True
    # 较长且非常见英文词
    if len(low) >= 5 and low.isalpha():
        return True
    return False
