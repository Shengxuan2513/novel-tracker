"""
Local Relay Server for Browser Relay (解决“不让看”与强人机盾拦截).
Receives rendered chapter HTML/text from the Tampermonkey userscript or browser extension,
cleans the content, and appends/exports it to local TXT, EPUB, and JSON formats.
"""

import asyncio
import json
import os
import re
from typing import Dict
from aiohttp import web

from core.heuristic_extractor import HeuristicExtractor
from core.pipeline import RegexCleaningPipeline
from core.formatters import TxtFormatter, EpubFormatter, JsonFormatter
from core.paths import downloads_dir
from core.safe_publish import capture_states, publish_outputs
from pathlib import Path


class RelayServer:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765, output_dir=None):
        self.host = host
        self.port = port
        self.output_dir = output_dir or downloads_dir()
        self.extractor = HeuristicExtractor()
        self.pipeline = RegexCleaningPipeline(min_char_length=200)
        self.books_cache: Dict[str, list] = {}
        os.makedirs(self.output_dir, exist_ok=True)

    async def handle_cors(self, request: web.Request) -> web.Response:
        """Handle CORS preflight OPTIONS request."""
        return web.Response(
            status=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
            }
        )

    async def handle_ping(self, request: web.Request) -> web.Response:
        """Health check endpoint."""
        return web.json_response(
            {"status": "ok", "service": "NovelTracker Relay Server", "port": self.port},
            headers={"Access-Control-Allow-Origin": "*"}
        )

    async def handle_relay(self, request: web.Request) -> web.Response:
        """
        Receives chapter payload from browser Tampermonkey script.
        """
        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"status": "error", "message": "Invalid JSON payload"},
                status=400,
                headers={"Access-Control-Allow-Origin": "*"}
            )

        book_title = data.get("book_title", "").strip() or "未命名小说"
        chapter_title = data.get("chapter_title", "").strip() or "章节"
        raw_html = data.get("html", "")
        raw_text = data.get("text", "")
        source_url = data.get("url", "")
        author = data.get("author", "未知")

        # Extract & Clean
        if raw_html:
            extracted = self.extractor.extract_article_text(raw_html, url=source_url)
        else:
            extracted = raw_text

        try:
            clean_body = self.pipeline.clean_text(extracted, chapter_title=chapter_title, source_url=source_url)
        except Exception:
            clean_body = extracted.strip()

        char_len = len(clean_body)
        print(f"📥 [Relay 收到浏览器同步] 《{book_title}》 -> {chapter_title} (字数: {char_len})")

        # Save to TXT
        safe_title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", book_title).rstrip(". ") or "未命名小说"
        txt_path = str(Path(self.output_dir, f"《{safe_title}》.txt").resolve())
        expected = capture_states([txt_path])
        previous = Path(txt_path).read_text(encoding="utf-8") if os.path.exists(txt_path) else f"《{book_title}》\n作者：{author}\n【浏览器接力同步版】\n{'=' * 60}\n\n"
        with publish_outputs([txt_path], expected=expected) as staged:
            Path(staged[txt_path]).write_text(previous + f"\n\n{chapter_title}\n\n{clean_body}\n", encoding="utf-8")

        return web.json_response(
            {
                "status": "success",
                "message": f"成功同步《{book_title}》{chapter_title}",
                "character_count": char_len,
                "saved_txt": txt_path
            },
            headers={"Access-Control-Allow-Origin": "*"}
        )

    def start(self):
        """Starts the local relay receiver server."""
        app = web.Application()
        app.router.add_options("/api/relay", self.handle_cors)
        app.router.add_post("/api/relay", self.handle_relay)
        app.router.add_get("/api/ping", self.handle_ping)

        print("=" * 65)
        print(f"🛡️ 【NovelTracker 浏览器接力服务 (Relay Server)】已启动")
        print(f"🌐 监听地址: http://{self.host}:{self.port}")
        print(f"📁 数据落盘目录: {os.path.abspath(self.output_dir)}")
        print("💡 配合油猴脚本 `scripts/novel_relay.user.js`，可在浏览器中一键同步任何受保护小说！")
        print("按 Ctrl+C 可停止接力服务。")
        print("=" * 65 + "\n")

        web.run_app(app, host=self.host, port=self.port)


if __name__ == "__main__":
    server = RelayServer()
    server.start()
