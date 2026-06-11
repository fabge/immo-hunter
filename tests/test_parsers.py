"""Fixture tests for the brittle parts: scraper parsers, LLM response parsing,
storage state machine, notifier formatting.

Run from repo root:  python -m unittest discover -s tests
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hunter.models import Listing
from hunter.llm_filter import ModelChain
from hunter.run import llm_settings
from hunter.storage import Storage
from hunter.notifier import format_listing
from hunter.llm_filter import parse_llm_response
from hunter.scrapers.kleinanzeigen import KleinanzeigenScraper, BLOCK_RE
from hunter.scrapers.immoscout import ImmoscoutScraper, extract_expose_text
from hunter.scrapers.rss import RssScraper


# Synthetic page matching the structures kleinanzeigen serves as of 2026-06.
# If the site redesigns, update this fixture together with the regexes.
KLEINANZEIGEN_HTML = """
<body>
<article data-adid="3021456789" data-href="/s-anzeige/charmantes-altbauhaus/3021456789">
  <script type="application/ld+json">{"title":"Charmantes Altbauhaus mit Garten in Dossenheim","description":"Freistehendes Haus, 140 m² Wohnfläche, 5 Zimmer, ruhige Lage.\\nFußläufig zum Ortskern.","contentUrl":"https://img.kleinanzeigen.de/api/v1/prod-ads/images/abc.jpg"}</script>
  <i class="icon icon-pin-gray"></i> 69221 Dossenheim
  <p class="aditem-main--middle--price-shipping--price"> 649.000 € </p>
</article>
</body>
"""

# Trimmed real response item from api.mobile.immobilienscout24.de/search/list
# (captured 2026-06-11).
IS24_ITEM = {
    "id": "168475382",
    "title": "Ihr neues Zuhause zum Selbstverwirklichen mit Charme und Garten",
    "titlePicture": {"preview": "https://pictures.immobilienscout24.de/x.webp"},
    "address": {
        "line": "68219 Mannheim / Pfingstberg, Rheinau (unvollständige Adresse)",
        "postcode": "68219",
    },
    "attributes": [
        {"label": "", "value": "645.000 €"},
        {"label": "", "value": "168 m²"},
        {"label": "", "value": "7 Zi."},
    ],
    "realEstateType": "housebuy",
}

# Shape of api.mobile.immobilienscout24.de/expose/{id} (captured 2026-06-11).
IS24_EXPOSE = {
    "sections": [
        {"type": "TITLE", "title": "Ihr neues Zuhause"},
        {"type": "TEXT_AREA", "title": "Objektbeschreibung", "text": "Freistehendes Einfamilienhaus von 1953."},
        {"type": "TEXT_AREA", "title": "Lage", "text": "Ruhige Wohnlage im Mannheimer Süden."},
        {"type": "TEXT_AREA", "title": "", "text": "Ohne Titel."},
        {"type": "CONTACT"},
    ]
}


class KleinanzeigenParserTest(unittest.TestCase):
    def test_parse_block(self):
        blocks = BLOCK_RE.findall(KLEINANZEIGEN_HTML)
        self.assertEqual(len(blocks), 1)
        adid, href, body = blocks[0]
        listing = KleinanzeigenScraper()._parse_block(adid, href, body)
        self.assertEqual(listing.uid, "kleinanzeigen:3021456789")
        self.assertEqual(listing.url, "https://www.kleinanzeigen.de/s-anzeige/charmantes-altbauhaus/3021456789")
        self.assertEqual(listing.title, "Charmantes Altbauhaus mit Garten in Dossenheim")
        self.assertEqual(listing.price_eur, 649000)
        self.assertEqual(listing.sqm, 140.0)
        self.assertEqual(listing.rooms, 5.0)
        self.assertEqual(listing.plz, "69221")
        self.assertIn("Dossenheim", listing.location)
        self.assertIn("Fußläufig", listing.description)


class ImmoscoutParserTest(unittest.TestCase):
    def test_to_listing(self):
        listing = ImmoscoutScraper()._to_listing(IS24_ITEM)
        self.assertEqual(listing.uid, "immoscout24:168475382")
        self.assertEqual(listing.price_eur, 645000)
        self.assertEqual(listing.sqm, 168.0)
        self.assertEqual(listing.rooms, 7.0)
        self.assertEqual(listing.plz, "68219")
        self.assertEqual(listing.url, "https://www.immobilienscout24.de/expose/168475382")

    def test_extract_expose_text(self):
        text = extract_expose_text(IS24_EXPOSE)
        self.assertIn("Objektbeschreibung:\nFreistehendes Einfamilienhaus", text)
        self.assertIn("Lage:\nRuhige Wohnlage", text)
        self.assertIn("Ohne Titel.", text)
        self.assertNotIn("CONTACT", text)


class RssParserTest(unittest.TestCase):
    def test_entry_to_listing(self):
        entry = {
            "link": "https://www.immobilienscout24.de/expose/123456789",
            "title": "Haus in Schriesheim",
            "summary": "<p>Schönes Haus, 550.000 €, 130 m², 5 Zimmer</p>",
        }
        listing = RssScraper()._entry_to_listing(entry, "test")
        self.assertEqual(listing.uid, "rss:test:123456789")
        self.assertEqual(listing.price_eur, 550000)
        self.assertEqual(listing.sqm, 130.0)
        self.assertEqual(listing.rooms, 5.0)


class LlmResponseTest(unittest.TestCase):
    def test_plain_json(self):
        r = parse_llm_response('{"score": 8, "reasoning": "gut", "red_flags": "", "in_corridor": true}')
        self.assertEqual(r["score"], 8)
        self.assertTrue(r["in_corridor"])

    def test_fenced_json(self):
        r = parse_llm_response('```json\n{"score": 7, "reasoning": "ok", "red_flags": ""}\n```')
        self.assertEqual(r["score"], 7)

    def test_json_embedded_in_prose(self):
        r = parse_llm_response('Hier die Bewertung:\n{"score": 5, "reasoning": "naja", "red_flags": "B-Straße"}')
        self.assertEqual(r["score"], 5)
        self.assertEqual(r["red_flags"], "B-Straße")

    def test_score_clamped(self):
        self.assertEqual(parse_llm_response('{"score": 15}')["score"], 10)
        self.assertEqual(parse_llm_response('{"score": -3}')["score"], 0)


def _listing(**kw) -> Listing:
    base = dict(
        source="kleinanzeigen",
        source_id="1",
        url="https://example.com/1",
        title="Haus A",
        price_eur=500000,
        sqm=140.0,
        location="69221 Dossenheim",
    )
    base.update(kw)
    return Listing(**base)


class StorageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.storage = Storage(str(Path(self.tmp.name) / "test.db"))

    def tearDown(self):
        self.storage.close()
        self.tmp.cleanup()

    def test_upsert_new_seen_changed(self):
        self.assertEqual(self.storage.upsert(_listing()), "new")
        self.assertEqual(self.storage.upsert(_listing()), "seen")
        # price drop -> changed, evaluation + notification reset
        self.storage.save_evaluation("kleinanzeigen:1", 8, "gut", "", True)
        self.storage.mark_notified("kleinanzeigen:1")
        self.assertEqual(self.storage.upsert(_listing(price_eur=450000)), "changed")
        rows = self.storage.unevaluated()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["price_eur"], 450000)
        self.assertIsNone(rows[0]["notified_at"])

    def test_cross_source_notification_dedupe(self):
        # same house on two portals -> identical content hash
        self.storage.upsert(_listing())
        self.storage.upsert(_listing(source="immoscout24", source_id="99", url="https://example.com/99"))
        self.storage.save_evaluation("kleinanzeigen:1", 8, "gut", "", True)
        self.storage.save_evaluation("immoscout24:99", 8, "gut", "", True)
        pending = self.storage.pending_notification(7)
        self.assertEqual(len(pending), 2)
        self.storage.mark_notified("kleinanzeigen:1")
        # the duplicate under the other uid must no longer be pending
        self.assertEqual(len(self.storage.pending_notification(7)), 0)

    def test_update_description(self):
        self.storage.upsert(_listing(description=""))
        self.storage.update_description("kleinanzeigen:1", "Lage: ruhig")
        self.assertEqual(self.storage.unevaluated()[0]["description"], "Lage: ruhig")


class LlmSettingsTest(unittest.TestCase):
    CONFIG = {"llm_backend": "cli", "llm_model": "claude-sonnet-4-6"}

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_config_defaults(self):
        self.assertEqual(llm_settings(self.CONFIG), ("cli", ["claude-sonnet-4-6"], ""))

    @mock.patch.dict(
        os.environ,
        {
            "LLM_BACKEND": "openai",
            "LLM_MODEL": "deepseek-v4-flash-free, glm-5.1",
            "LLM_BASE_URL": "https://opencode.ai/zen/v1",
        },
    )
    def test_env_overrides_config_with_chain(self):
        self.assertEqual(
            llm_settings(self.CONFIG),
            ("openai", ["deepseek-v4-flash-free", "glm-5.1"], "https://opencode.ai/zen/v1"),
        )

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_yaml_list_chain(self):
        backend, models, _ = llm_settings({"llm_model": ["free-model", "paid-model"]})
        self.assertEqual(models, ["free-model", "paid-model"])


class ModelChainTest(unittest.TestCase):
    def test_falls_back_on_failure(self):
        def fn(model):
            if model == "free":
                raise RuntimeError("rate limited")
            return {"score": 7}

        chain = ModelChain(["free", "paid"])
        model, result = chain.call(fn)
        self.assertEqual(model, "paid")
        self.assertEqual(result["score"], 7)

    def test_primary_skipped_after_max_failures(self):
        calls = []

        def fn(model):
            calls.append(model)
            if model == "free":
                raise RuntimeError("rate limited")
            return {}

        chain = ModelChain(["free", "paid"], max_failures=2)
        chain.call(fn)  # free fails (1), paid succeeds
        chain.call(fn)  # free fails (2), paid succeeds
        chain.call(fn)  # free now skipped entirely
        self.assertEqual(calls, ["free", "paid", "free", "paid", "paid"])

    def test_raises_when_all_exhausted(self):
        def fn(model):
            raise RuntimeError("down")

        chain = ModelChain(["a", "b"], max_failures=1)
        with self.assertRaises(RuntimeError):
            chain.call(fn)
        self.assertEqual(chain.active(), [])


class NotifierFormatTest(unittest.TestCase):
    def test_html_escaping(self):
        row = {
            "llm_score": 8,
            "source": "kleinanzeigen",
            "title": "Haus <mit> Garten & *Charme*",
            "price_eur": 500000,
            "sqm": 140.0,
            "location": "Dossenheim",
            "llm_reasoning": "Gute Lage <5 Min zur OEG",
            "llm_red_flags": "",
            "url": "https://example.com/1",
        }
        text = format_listing(row)
        self.assertIn("Haus &lt;mit&gt; Garten &amp; *Charme*", text)
        self.assertIn("&lt;5 Min", text)
        self.assertIn("<b>Score 8/10</b>", text)


if __name__ == "__main__":
    unittest.main()
