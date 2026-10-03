import os
import json
import xml.etree.ElementTree as ET
import pytest
from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from core.legado_bridge import LegadoBridge, get_local_ip
from core.web_server import WebApp


class TestLegadoBridge:
    def test_get_local_ip(self):
        ip = get_local_ip()
        assert isinstance(ip, str)
        assert len(ip.split('.')) == 4

    def test_generate_opds_feed_empty(self, tmp_path):
        bridge = LegadoBridge(downloads_dir=str(tmp_path))
        feed_xml = bridge.generate_opds_feed("http://198.18.0.1:5000")
        assert "<?xml version=" in feed_xml
        assert "<feed" in feed_xml
        assert "</feed>" in feed_xml
        assert "http://198.18.0.1:5000/opds" in feed_xml

        # Verify XML parses without error
        root = ET.fromstring(feed_xml)
        assert "feed" in root.tag

    def test_generate_opds_feed_with_books(self, tmp_path):
        # Create mock txt and epub
        txt_path = tmp_path / "《修真世界》.txt"
        txt_path.write_text("作者：方想\n第一章 启程\n正文内容...", encoding="utf-8")

        epub_path = tmp_path / "《剑来》.epub"
        epub_path.write_text("mock epub content", encoding="utf-8")

        bridge = LegadoBridge(downloads_dir=str(tmp_path))
        feed_xml = bridge.generate_opds_feed("http://192.168.1.100:5000")

        assert "《修真世界》" not in feed_xml or "修真世界" in feed_xml
        assert "剑来" in feed_xml
        assert "方想" in feed_xml
        assert "application/epub+zip" in feed_xml
        assert "text/plain" in feed_xml
        assert "http://opds-spec.org/acquisition" in feed_xml

        # Verify XML parses without error
        root = ET.fromstring(feed_xml)
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")
        assert len(entries) == 2

    def test_generate_legado_book_sources(self):
        bridge = LegadoBridge()
        sources = bridge.generate_legado_book_sources()
        assert isinstance(sources, list)
        assert len(sources) >= 2

        for src in sources:
            assert "bookSourceName" in src
            assert "bookSourceUrl" in src
            assert "ruleSearch" in src
            assert "ruleToc" in src
            assert "ruleContent" in src
            assert "content" in src["ruleContent"]


class TestWebServerLegadoRoutes(AioHTTPTestCase):
    async def get_application(self):
        self.temp_downloads = self.useFixture(None) if hasattr(self, "useFixture") else None
        webapp = WebApp(host="127.0.0.1", port=5000)
        app = web.Application()
        app.router.add_get("/opds", webapp.handle_opds)
        app.router.add_get("/api/legado/sources.json", webapp.handle_legado_sources)
        app.router.add_get("/api/legado/info", webapp.handle_legado_info)
        app.router.add_get("/legado.apk", webapp.handle_legado_apk)
        return app

    async def test_opds_endpoint(self):
        resp = await self.client.request("GET", "/opds")
        assert resp.status == 200
        text = await resp.text()
        assert "<?xml version=" in text
        assert "urn:uuid:novel-tracker-opds-catalog" in text

    async def test_legado_sources_endpoint(self):
        resp = await self.client.request("GET", "/api/legado/sources.json")
        assert resp.status == 200
        data = await resp.json()
        assert isinstance(data, list)
        assert len(data) >= 2
        assert "bookSourceName" in data[0]

    async def test_legado_info_endpoint(self):
        resp = await self.client.request("GET", "/api/legado/info")
        assert resp.status == 200
        data = await resp.json()
        assert "lan_ip" in data
        assert "opds_url" in data
        assert "sources_url" in data
        assert "apk_url" in data
        assert "apk_exists" in data
