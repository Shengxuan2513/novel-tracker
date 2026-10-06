"""Exercise local companion downloads without requiring an actual APK."""
import tempfile
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase
from core.web_server import WebApp


class TestReaderApk(AioHTTPTestCase):
    async def get_application(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "client").mkdir()
        self.addCleanup(patch.stopall)
        patch("core.web_server.__file__", str(self.root / "core" / "web_server.py")).start()
        server = WebApp(host="127.0.0.1")
        app = web.Application()
        app.router.add_get("/legado-fixed.apk", server.handle_legado_apk)
        app.router.add_get("/legado.apk", server.handle_legado_apk)
        return app

    async def test_missing_fixed_apk_is_not_replaced_by_original(self):
        response = await self.client.get("/legado-fixed.apk", allow_redirects=False)
        assert response.status == 404
        assert "Location" not in response.headers

    async def test_fixed_apk_download_and_range(self):
        content = b"PK" + bytes(range(64))
        (self.root / "client" / "legado-epubfix-arm64.apk").write_bytes(content)
        response = await self.client.get("/legado-fixed.apk")
        assert response.status == 200
        assert await response.read() == content
        response = await self.client.get("/legado-fixed.apk", headers={"Range": "bytes=0-1"})
        assert response.status == 206
        assert await response.read() == b"PK"
        assert response.headers["Content-Range"] == f"bytes 0-1/{len(content)}"

    async def test_original_download_remains_available(self):
        content = b"original package"
        (self.root / "client" / "legado-3.26-arm64.apk").write_bytes(content)
        response = await self.client.get("/legado.apk")
        assert response.status == 200
        assert await response.read() == content
