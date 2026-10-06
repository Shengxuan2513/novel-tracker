"""Regression coverage for launching outside the project and multi-interface access."""

import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import Mock
from urllib.error import URLError
from urllib.parse import urlsplit

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from core import legado_bridge, web_server


ATOM = "{http://www.w3.org/2005/Atom}"


def test_legado_serves_project_downloads_from_another_working_directory(tmp_path, monkeypatch):
    import cli

    project = tmp_path / "project"
    downloads = project / "downloads"
    downloads.mkdir(parents=True)
    (downloads / "project-book.txt").write_text("作者：测试\n项目书库正文", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "downloads").mkdir(parents=True)
    (elsewhere / "downloads" / "wrong-book.txt").write_text("其他目录的正文", encoding="utf-8")
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(cli, "__file__", str(project / "cli.py"))
    monkeypatch.setattr(legado_bridge, "get_local_ip", lambda: "192.168.137.1")
    monkeypatch.setattr("urllib.request.urlopen", Mock(side_effect=URLError("not running")))

    applications = []
    original_app = web_server.WebApp

    def make_app(**kwargs):
        app = original_app(**kwargs)
        app.start = Mock()
        applications.append(app)
        return app

    monkeypatch.setattr(web_server, "WebApp", make_app)
    cli.cmd_legado(port=5000)

    app, = applications
    app.start.assert_called_once_with(auto_open=False)
    assert Path(app.output_dir) == downloads
    feed = ET.fromstring(legado_bridge.LegadoBridge(app.output_dir).generate_opds_feed("http://192.168.137.1:5000"))
    assert [entry.find(f"{ATOM}title").text for entry in feed.findall(f"{ATOM}entry")] == ["project-book"]


class TestOpdsRequestAddress(AioHTTPTestCase):
    async def get_application(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.filename = "《测试小说》.txt"
        self.content = "作者：测试\n第一章 正文"
        (Path(self.directory.name) / self.filename).write_bytes(self.content.encode("utf-8"))
        webapp = web_server.WebApp(host="127.0.0.1", port=5000, output_dir=self.directory.name)
        app = web.Application()
        app.router.add_get("/opds", webapp.handle_opds)
        app.router.add_get("/api/download/{filename}", webapp.handle_download_file)
        return app

    async def test_feed_links_use_request_interface_and_port(self):
        for host in ("192.168.137.1:5000", "10.22.53.215:8765", "localhost:8080"):
            with self.subTest(host=host):
                response = await self.client.get("/opds", headers={"Host": host})
                assert response.status == 200
                feed = ET.fromstring(await response.text())
                links = feed.findall(f"{ATOM}link")
                assert {link.attrib["rel"] for link in links} == {"self", "start"}
                assert all(link.attrib["href"] == f"http://{host}/opds" for link in links)
                entry = feed.find(f"{ATOM}entry")
                assert entry is not None
                acquisition = entry.find(f"{ATOM}link")
                url = urlsplit(acquisition.attrib["href"])
                assert url.scheme == "http"
                assert url.netloc == host
                download = await self.client.get(url.path, headers={"Host": host})
                assert download.status == 200
                assert await download.text() == self.content
