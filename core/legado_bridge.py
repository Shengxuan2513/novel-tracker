"""
Legado (阅读 3.0) Integration Bridge for NovelTracker.
Enables bidirectional synergy between NovelTracker and Legado:
1. OPDS Catalog Feed: Exposes local downloads as an OPDS standard book repository for 1-tap wireless sync.
2. BookSource Exporter: Generates Legado-compatible JSON book sources from verified scrapers.
3. APK Host & Distribution: Manages local Legado arm64 builds for mobile sideloading.
"""

import hashlib
import json
import os
import re
import socket
import urllib.parse
from datetime import datetime, timezone
from typing import Dict, List, Optional
from xml.sax.saxutils import escape


def get_local_ip() -> str:
    """Detect primary LAN IP of the host machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Does not actually establish connection, just routes IP
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = '127.0.0.1'
    finally:
        s.close()
    return ip


class LegadoBridge:
    def __init__(self, downloads_dir: str = "downloads", client_dir: str = "client"):
        self.downloads_dir = downloads_dir
        self.client_dir = client_dir

    def generate_opds_feed(self, host_url: str) -> str:
        """
        Generates standard OPDS 1.2 Atom XML catalog feed for Legado 3.0.
        """
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        books = []

        if os.path.exists(self.downloads_dir):
            for fname in os.listdir(self.downloads_dir):
                if fname.lower().endswith((".epub", ".txt")):
                    fpath = os.path.join(self.downloads_dir, fname)
                    size_mb = os.path.getsize(fpath) / (1024 * 1024)
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

                    # Extract book name & format
                    clean_name = re.sub(r'[《》]', '', os.path.splitext(fname)[0]).strip()
                    is_epub = fname.lower().endswith(".epub")
                    mime_type = "application/epub+zip" if is_epub else "text/plain"

                    # Try to extract author
                    author = "未知"
                    if is_epub:
                        try:
                            import ebooklib
                            from ebooklib import epub
                            b = epub.read_epub(fpath)
                            c = b.get_metadata('DC', 'creator')
                            if c:
                                author = c[0][0]
                        except Exception:
                            pass
                    else:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            head = f.read(500)
                            m = re.search(r'作\s*者[：:\s]*([^\s,，。；\n\r<]{1,15})', head)
                            if m:
                                author = m.group(1).strip()

                    encoded_name = urllib.parse.quote(fname)
                    download_url = f"{host_url.rstrip('/')}/api/download/{encoded_name}"

                    books.append({
                        "title": clean_name,
                        "filename": fname,
                        "author": author,
                        "mime": mime_type,
                        "size_mb": f"{size_mb:.2f} MB",
                        "updated": mtime,
                        "download_url": download_url
                    })

        # Build Atom XML
        xml_entries = []
        for b in books:
            entry = f"""  <entry>
    <title>{escape(b['title'])}</title>
    <id>urn:novel-tracker:book:{hashlib.md5(b['filename'].encode('utf-8')).hexdigest()}</id>
    <author>
      <name>{escape(b['author'])}</name>
    </author>
    <updated>{b['updated']}</updated>
    <summary>NovelTracker 完整精校版 ({b['size_mb']})</summary>
    <link rel="http://opds-spec.org/acquisition" href="{escape(b['download_url'])}" type="{b['mime']}"/>
  </entry>"""
            xml_entries.append(entry)

        feed_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opds="http://opds-spec.org/2010/catalog">
  <id>urn:uuid:novel-tracker-opds-catalog</id>
  <title>NovelTracker 本地私有书库 (Legado专属)</title>
  <updated>{now_str}</updated>
  <author>
    <name>NovelTracker</name>
  </author>
  <link rel="self" href="{host_url.rstrip('/')}/opds" type="application/atom+xml;profile=opds-catalog;kind=navigation"/>
  <link rel="start" href="{host_url.rstrip('/')}/opds" type="application/atom+xml;profile=opds-catalog;kind=navigation"/>
{chr(10).join(xml_entries)}
</feed>"""
        return feed_xml

    def generate_legado_book_sources(self) -> List[dict]:
        """
        Converts NovelTracker's top verified scrapers into Legado 3.0 standard BookSource format.
        """
        sources = [
            {
                "bookSourceName": "NovelTracker - 飘天文学 (优质极速源)",
                "bookSourceUrl": "https://www.piaotia.com",
                "bookSourceType": 0,
                "enabled": True,
                "enabledExplore": True,
                "weight": 100,
                "customOrder": 1,
                "header": "{\"User-Agent\": \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0\"}",
                "searchUrl": "/modules/article/search.php?searchtype=articlename&searchkey={{key}}",
                "ruleSearch": {
                  "bookList": "tr:has(td.odd)",
                  "name": "td:nth-child(1) a@text",
                  "author": "td:nth-child(3)@text",
                  "bookUrl": "td:nth-child(1) a@href",
                  "latestChapter": "td:nth-child(2) a@text"
                },
                "ruleToc": {
                  "chapterList": "div.centent li a",
                  "chapterName": "text",
                  "chapterUrl": "href"
                },
                "ruleContent": {
                  "content": "div#content@textNodes"
                }
            },
            {
                "bookSourceName": "NovelTracker - 速读谷 (稳定多页源)",
                "bookSourceUrl": "https://www.sudugu.cc",
                "bookSourceType": 0,
                "enabled": True,
                "enabledExplore": True,
                "weight": 95,
                "customOrder": 2,
                "header": "{\"User-Agent\": \"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0\"}",
                "searchUrl": "/search.html?searchtype=all&searchkey={{key}}",
                "ruleSearch": {
                  "bookList": ".book-item, li:has(a.book-name)",
                  "name": "a.book-name@text",
                  "author": "span.author@text",
                  "bookUrl": "a.book-name@href"
                },
                "ruleToc": {
                  "chapterList": "#chapterlist a, .chapter-list a",
                  "chapterName": "text",
                  "chapterUrl": "href"
                },
                "ruleContent": {
                  "content": "#content@textNodes",
                  "nextContentUrl": "a:contains(下一页)@href"
                }
            }
        ]
        return sources
