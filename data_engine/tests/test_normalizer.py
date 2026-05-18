"""normalizer 文本清洗 + 切片测试。"""

from __future__ import annotations

import unittest

from data_engine.normalizer import (
    html_to_text,
    looks_like_disambiguation,
    split_long,
    wikitext_to_text,
)


class HtmlToTextTests(unittest.TestCase):
    def test_strips_tags(self):
        html = "<html><body><p>Hello <b>World</b></p></body></html>"
        self.assertEqual(html_to_text(html), "Hello World")

    def test_skips_script_and_style(self):
        html = "<div><script>var x=1;</script><p>hi</p><style>.a{}</style></div>"
        self.assertEqual(html_to_text(html), "hi")

    def test_block_tags_become_newlines(self):
        html = "<p>line1</p><p>line2</p>"
        text = html_to_text(html)
        self.assertIn("line1", text)
        self.assertIn("line2", text)
        self.assertIn("\n", text)


class WikitextToTextTests(unittest.TestCase):
    def test_drops_templates_and_refs(self):
        wikitext = "Python is {{infobox programming language}}a language.<ref>cite</ref>"
        result = wikitext_to_text(wikitext)
        self.assertIn("Python is", result)
        self.assertIn("a language", result)
        self.assertNotIn("{{", result)
        self.assertNotIn("<ref", result)

    def test_link_label_kept(self):
        self.assertIn("dynamic", wikitext_to_text("[[dynamic typing|dynamic]]"))
        self.assertIn("Apple", wikitext_to_text("[[Apple]]"))

    def test_headings_and_bold(self):
        self.assertIn("History", wikitext_to_text("== History =="))
        self.assertEqual(wikitext_to_text("'''bold'''"), "bold")


class DisambiguationTests(unittest.TestCase):
    def test_english_pattern(self):
        self.assertTrue(looks_like_disambiguation("Python may refer to: ..."))

    def test_chinese_pattern(self):
        self.assertTrue(looks_like_disambiguation("Python 可以指：编程语言、蛇等"))

    def test_normal_extract_not_disambig(self):
        self.assertFalse(looks_like_disambiguation("Python is a high-level programming language."))


class SplitLongTests(unittest.TestCase):
    def test_short_text_not_split(self):
        self.assertEqual(split_long("hello world", max_chars=100), ["hello world"])

    def test_empty_text_yields_empty(self):
        self.assertEqual(split_long("   ", max_chars=10), [])

    def test_splits_on_sentence_boundary(self):
        text = "Sentence one. Sentence two. Sentence three. Sentence four. Sentence five."
        chunks = split_long(text, max_chars=30, overlap=0)
        # 切片不应在词内中断
        for chunk in chunks:
            self.assertTrue(chunk.endswith(".") or chunk == chunks[-1])

    def test_overlap_validates(self):
        with self.assertRaises(ValueError):
            split_long("abc", max_chars=5, overlap=10)
        with self.assertRaises(ValueError):
            split_long("abc", max_chars=0)


if __name__ == "__main__":
    unittest.main()
