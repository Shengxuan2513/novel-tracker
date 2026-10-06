import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase

from core.formatters.epub_formatter import EpubFormatter
from core.legado_bridge import LegadoBridge
from core.web_server import WebApp
from core.versioned_download import file_version, snapshot_file, StaleDownload
from unittest.mock import patch


class TestVersionedEpubDownload(AioHTTPTestCase):
    async def get_application(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "book.epub"
        EpubFormatter.export(str(self.path), {"title": "测试小说", "author": "测试"},
                             [(1, "第232章", "正文一"), (2, "第233章", "正文二")])
        webapp = WebApp(output_dir=self.directory.name)
        app = web.Application()
        app.router.add_get("/api/download/version/{version}/{filename}", webapp.handle_download_file)

        async def cleanup(_):
            yield
            self.directory.cleanup()

        app.cleanup_ctx.append(cleanup)
        return app

    async def test_range_reads_local_zip_header_at_real_chapter_offset(self):
        mtime = self.path.stat().st_mtime_ns
        version = file_version(self.path.stat())
        with zipfile.ZipFile(self.path) as archive:
            offset = archive.getinfo("OEBPS/chapter_2.xhtml").header_offset
        response = await self.client.get(f"/api/download/version/{version}/book.epub",
                                         headers={"Range": f"bytes={offset}-{offset+3}"})
        assert response.status == 206
        assert await response.read() == b"PK\x03\x04"

    async def test_stale_version_refuses_to_serve_new_zip_with_old_offsets(self):
        mtime = self.path.stat().st_mtime_ns
        version = file_version(self.path.stat())
        os.utime(self.path, ns=(mtime, mtime + 1_000_000_000))
        response = await self.client.get(f"/api/download/version/{version}/book.epub",
                                         headers={"Range": "bytes=0-3"})
        assert response.status == 410
        assert "已更新" in await response.text()
        latest = response.headers["X-NovelTracker-Latest-URL"]
        fresh = await self.client.get(latest, headers={"Range": "bytes=0-3"})
        assert fresh.status == 206
        assert await fresh.read() == b"PK\x03\x04"

    async def test_feed_keeps_identity_but_changes_download_url_after_update(self):
        bridge = LegadoBridge(downloads_dir=self.directory.name)
        before = ET.fromstring(bridge.generate_opds_feed("http://192.168.137.1:5000"))
        mtime = self.path.stat().st_mtime_ns
        version = file_version(self.path.stat())
        os.utime(self.path, ns=(mtime, mtime + 1_000_000_000))
        after = ET.fromstring(bridge.generate_opds_feed("http://192.168.137.1:5000"))
        ns = {"a": "http://www.w3.org/2005/Atom"}
        assert before.find("a:entry/a:id", ns).text == after.find("a:entry/a:id", ns).text
        first = before.find("a:entry/a:link", ns).attrib["href"]
        second = after.find("a:entry/a:link", ns).attrib["href"]
        assert first != second
        assert second.endswith("/book.epub")

    async def test_in_place_update_after_handler_does_not_change_response_bytes(self):
        version = file_version(self.path.stat())
        original = self.path.read_bytes()
        snapshot = snapshot_file(self.path, version)
        self.path.write_bytes(b"replacement book")
        os.utime(self.path, ns=(1, self.path.stat().st_mtime_ns + 1_000_000_000))
        assert snapshot.read_bytes() == original
        stale = await self.client.get(f"/api/download/version/{version}/book.epub")
        assert stale.status == 410

    async def test_update_during_copy_is_rejected(self):
        version = file_version(self.path.stat())
        import shutil
        copy = shutil.copyfileobj
        def replace_during_copy(source, output):
            copy(source, output)
            self.path.write_bytes(b"changed during copy")
            os.utime(self.path, ns=(1, self.path.stat().st_mtime_ns + 1_000_000_000))
        with patch("core.versioned_download.shutil.copyfileobj", side_effect=replace_during_copy):
            response = await self.client.get(f"/api/download/version/{version}/book.epub")
        assert response.status == 410
        assert not list((self.path.parent / ".download-snapshots").iterdir())

    async def test_http_validators_and_head(self):
        version = file_version(self.path.stat())
        url = f"/api/download/version/{version}/book.epub"
        response = await self.client.head(url)
        assert response.status == 200
        assert int(response.headers["Content-Length"]) == self.path.stat().st_size
        assert await response.read() == b""
        etag = response.headers["ETag"]
        response = await self.client.get(url, headers={"If-Match": etag, "Range": "bytes=0-3"})
        assert response.status == 206
        assert await response.read() == b"PK\x03\x04"
        response = await self.client.get(url, headers={"If-Match": '"wrong"'})
        assert response.status == 412
        response = await self.client.get(url, headers={"If-None-Match": etag})
        assert response.status == 304

    async def test_same_timestamp_different_size_changes_version(self):
        before = self.path.stat()
        old = file_version(before)
        self.path.write_bytes(b"different size")
        os.utime(self.path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert file_version(self.path.stat()) != old
        response = await self.client.get(f"/api/download/version/{old}/book.epub")
        assert response.status == 410

    async def test_encoded_filename_cannot_escape_downloads(self):
        response = await self.client.get("/api/download/version/anything/..%2Fsecret.epub")
        assert response.status == 404

    async def test_replacement_between_snapshot_and_send_uses_snapshot(self):
        version = file_version(self.path.stat())
        original = self.path.read_bytes()
        def snapshot_then_replace(path, requested):
            saved = snapshot_file(path, requested)
            self.path.write_bytes(b"replacement after handler check")
            return saved
        with patch("core.versioned_download.snapshot_file", side_effect=snapshot_then_replace):
            response = await self.client.get(f"/api/download/version/{version}/book.epub")
            assert response.status == 200
            assert await response.read() == original

    async def test_unicode_and_literal_percent_filename(self):
        import urllib.parse
        named = self.path.with_name("《测试》%2F.epub")
        self.path.rename(named)
        version = file_version(named.stat())
        response = await self.client.get(f"/api/download/version/{version}/{urllib.parse.quote(named.name, safe='')}")
        assert response.status == 200
        assert await response.read() == named.read_bytes()

    async def test_unchanged_version_reuses_snapshot(self):
        version = file_version(self.path.stat())
        first = snapshot_file(self.path, version)
        with patch("core.versioned_download.shutil.copyfileobj", side_effect=AssertionError("unexpected recopy")):
            second = snapshot_file(self.path, version)
        assert first == second
