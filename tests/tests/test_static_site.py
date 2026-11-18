"""Regression checks for the static site. Run: python3 -m unittest discover -s tests"""
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Document(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.ids = set()
        self.links = []
        self.details = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "details":
            self.details.append(attrs)


class StaticSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / "agents.json").read_text())
        cls.documents = {file: Document(file.read_text()) for file in ROOT.rglob("*.html")}

    def test_setup_content_is_exposed(self):
        for setup in self.data["usecases"]:
            with self.subTest(setup=setup["id"]):
                source = (ROOT / "use-cases" / setup["id"] / "index.html").read_text()
                self.assertIn('class="ucx-answer"', source)
                self.assertIn(html.escape(setup["answer"], quote=True), source)
                self.assertLess(source.index('class="ucx-answer"'), source.index('class="ucx-setup"'))
                self.assertLess(source.index('id="howItWorks"'), source.index('<details'))
                if setup.get("for"):
                    self.assertIn('class="ucx-fit"', source)
                if setup.get("watchOut"):
                    self.assertIn(html.escape(setup["watchOut"], quote=True), source)
                for alternative in setup["alternatives"]:
                    # Full tradeoffs, not only the short card labels, must survive.
                    self.assertIn(html.escape(alternative["when"][1:], quote=True), source)
                details = Document(source).details
                self.assertEqual(len(details), len(setup["workflows"]) + 1)
                self.assertTrue(all("open" in d for d in details[:-1]))
                self.assertNotIn("open", details[-1])

    def test_internal_links_resolve(self):
        for file, document in self.documents.items():
            for link in document.links:
                url = urlsplit(link)
                if url.netloc and url.netloc != "agentictools.design":
                    continue
                if url.scheme and url.scheme not in ("http", "https"):
                    continue
                destination = (ROOT / unquote(url.path).lstrip("/")) if url.path.startswith("/") else file.parent / unquote(url.path)
                if not url.path:
                    destination = file
                if destination.is_dir():
                    destination /= "index.html"
                destination = destination.resolve()
                with self.subTest(page=str(file.relative_to(ROOT)), link=link):
                    self.assertTrue(destination.exists())
                    if url.fragment and destination in self.documents:
                        self.assertIn(unquote(url.fragment), self.documents[destination].ids)

    def test_breadcrumbs(self):
        for agent in self.data["agents"]:
            source = (ROOT / "agents" / agent["id"] / "index.html").read_text()
            self.assertIn('/?category=%s#all' % agent["category"], source)
        for workflow in self.data["workflows"]:
            source = (ROOT / "workflows" / workflow["id"] / "index.html").read_text()
            self.assertNotIn('<span>/</span><span>/</span>', source)

    def test_directory_search_has_a_name(self):
        source = (ROOT / "index.html").read_text()
        self.assertIn('id="q" aria-label="Search agents, makers and uses"', source)


if __name__ == "__main__":
    unittest.main()
