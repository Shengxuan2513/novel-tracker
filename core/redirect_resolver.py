"""
Asynchronous Search Engine Redirect Resolver.
Resolves encrypted/redirect search links (e.g., baidu.com/link?url=..., so.com/link?m=...)
to canonical target novel website URLs before domain blacklisting and catalog extraction.
"""

import asyncio
import re
import urllib.parse
from typing import Dict, List, Optional
import httpx
from bs4 import BeautifulSoup


class RedirectResolver:
    def __init__(self, timeout: float = 6.0):
        self.timeout = timeout
        self._cache: Dict[str, str] = {}
        self.headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/124.0.0.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def is_redirect_url(self, url: str) -> bool:
        """Check if a URL is an encrypted or intermediary search jump URL."""
        if not url:
            return False
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        return (
            "baidu.com" in netloc and "/link" in parsed.path
        ) or (
            "so.com" in netloc and "/link" in parsed.path
        ) or (
            "sogou.com" in netloc and "/link" in parsed.path
        )

    async def resolve_single_url(self, url: str, client: Optional[httpx.AsyncClient] = None) -> str:
        """
        Resolves a single search engine intermediary link to its real destination URL.
        """
        if not url:
            return ""

        url = url.strip()
        if not self.is_redirect_url(url):
            return url

        if url in self._cache:
            return self._cache[url]

        should_close = False
        if client is None:
            client = httpx.AsyncClient(
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
                verify=False
            )
            should_close = True

        resolved_url = url
        try:
            # 1. Handle 360 Search Jump Links (so.com/link)
            if "so.com" in url:
                resp = await client.get(url, timeout=self.timeout)
                if resp.status_code == 200:
                    text = resp.text
                    # Check JavaScript window.location.replace
                    m = re.search(r'replace\(["\']([^"\']+)["\']\)', text)
                    if m and m.group(1).startswith("http"):
                        resolved_url = m.group(1)
                    else:
                        # Check meta http-equiv="refresh"
                        m2 = re.search(r'URL=["\']?([^"\' >]+)', text, re.IGNORECASE)
                        if m2 and m2.group(1).startswith("http"):
                            resolved_url = m2.group(1)
                        else:
                            final_str = str(resp.url)
                            if not self.is_redirect_url(final_str):
                                resolved_url = final_str

            # 2. Handle Baidu Search Jump Links (baidu.com/link)
            elif "baidu.com" in url:
                # First attempt HEAD request to read Location header quickly
                try:
                    head_resp = await client.head(url, follow_redirects=False, timeout=self.timeout)
                    loc = head_resp.headers.get("Location") or head_resp.headers.get("location")
                    if loc and loc.startswith("http") and "baidu.com" not in loc:
                        resolved_url = loc
                except Exception:
                    pass

                # If HEAD failed or gave no external Location, follow redirects with GET
                if resolved_url == url:
                    resp = await client.get(url, timeout=self.timeout)
                    final_str = str(resp.url)
                    if final_str.startswith("http") and not self.is_redirect_url(final_str):
                        resolved_url = final_str
                    else:
                        # Inspect HTML for window.location or meta refresh
                        text = resp.text
                        m = re.search(r'replace\(["\']([^"\']+)["\']\)', text) or re.search(r'URL=["\']?([^"\' >]+)', text, re.IGNORECASE)
                        if m and m.group(1).startswith("http") and "baidu.com" not in m.group(1):
                            resolved_url = m.group(1)

            # 3. Handle Sogou Search Jump Links (sogou.com/link)
            elif "sogou.com" in url:
                resp = await client.get(url, timeout=self.timeout)
                final_str = str(resp.url)
                if final_str.startswith("http") and not self.is_redirect_url(final_str):
                    resolved_url = final_str

        except Exception:
            resolved_url = url
        finally:
            if should_close:
                await client.aclose()

        self._cache[url] = resolved_url
        return resolved_url

    async def resolve_all(self, urls: List[str], concurrency: int = 12) -> List[str]:
        """
        Concurrently resolves a batch of URLs with rate limiting.
        """
        if not urls:
            return []

        semaphore = asyncio.Semaphore(concurrency)
        resolved_list: List[str] = []

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
            verify=False
        ) as client:
            async def _worker(raw_url: str):
                async with semaphore:
                    res = await self.resolve_single_url(raw_url, client=client)
                    return res

            tasks = [_worker(u) for u in urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            seen = set()
            for r in results:
                if isinstance(r, str) and r.startswith("http") and r not in seen:
                    seen.add(r)
                    resolved_list.append(r)

        return resolved_list
