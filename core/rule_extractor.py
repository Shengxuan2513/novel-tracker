"""
Rule-based Novel Content and Catalog Extractor.
Loads declarative JSON source rules from sources/rules/ to provide high-precision,
instant DOM extraction for known novel sites, complementing heuristic extractors.
"""

import json
import os
import re
import urllib.parse
from typing import Dict, List, Optional, Tuple
from bs4 import BeautifulSoup
from core.parser import extract_chapter_number
from core.heuristic_extractor import HeuristicExtractor


class RuleBasedExtractor:
    def __init__(self, rules_dir: Optional[str] = None):
        if rules_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.rules_dir = os.path.join(base_dir, "sources", "rules")
        else:
            self.rules_dir = rules_dir

        self.rules: List[dict] = []
        self.domain_map: Dict[str, dict] = {}
        self.load_rules()

    def load_rules(self) -> None:
        """Load all JSON source rules from rules directory."""
        self.rules = []
        self.domain_map = {}
        if not os.path.exists(self.rules_dir):
            return

        for filename in os.listdir(self.rules_dir):
            if filename.endswith(".json"):
                path = os.path.join(self.rules_dir, filename)
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        rule = json.load(f)
                        self.rules.append(rule)
                        domains = rule.get("domains", [])
                        for d in domains:
                            self.domain_map[d.lower()] = rule
                except Exception:
                    pass

    def get_rule_for_url(self, url: str) -> Optional[dict]:
        """Find matching rule based on URL host."""
        if not url:
            return None
        parsed = urllib.parse.urlparse(url)
        netloc = parsed.netloc.lower()
        if ":" in netloc:
            netloc = netloc.split(":")[0]

        # Exact match or subdomain match
        for d, rule in self.domain_map.items():
            if netloc == d or netloc.endswith(f".{d}"):
                return rule
        return None

    def extract_catalog(self, html: str, base_url: str) -> List[Tuple[int, str, str, float]]:
        """
        Extract chapter catalog using matched rule.
        Returns: [(index, title, full_url, chapter_num), ...]
        """
        rule = self.get_rule_for_url(base_url)
        if not rule or "catalog" not in rule:
            return []

        cat_rule = rule["catalog"]
        selector = cat_rule.get("list_selector")
        if not selector:
            return []

        soup = BeautifulSoup(html, "html.parser")
        links = soup.select(selector)
        if not links:
            return []

        chapters: List[Tuple[int, str, str, float]] = []
        seen_urls = set()

        for idx, a in enumerate(links, 1):
            title = a.get_text(strip=True)
            href = a.get(cat_rule.get("url_attr", "href"), "")
            if not title or not href:
                continue

            full_url = urllib.parse.urljoin(base_url, href)
            if full_url in seen_urls:
                continue

            num, _ = extract_chapter_number(title)
            seen_urls.add(full_url)
            chapters.append((idx, title, full_url, num))

        return chapters

    def extract_content(self, html: str, url: str = "") -> Optional[str]:
        """
        Extract clean chapter content using matched rule.
        """
        rule = self.get_rule_for_url(url)
        if not rule or "content" not in rule:
            return None

        cont_rule = rule["content"]
        body_sel = cont_rule.get("body_selector")
        if not body_sel:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # 1. Remove noise elements
        for noise_sel in cont_rule.get("remove_selectors", []):
            for el in soup.select(noise_sel):
                el.decompose()

        # 2. Extract body
        body = soup.select_one(body_sel)
        if not body:
            return None

        # Convert <br> and <p> to newlines
        for br in body.find_all(["br", "p"]):
            br.replace_with("\n" + br.get_text() + "\n")

        raw_text = body.get_text()

        # 3. Clean specific regex noise patterns defined in rule
        for pat in cont_rule.get("clean_regexes", []):
            raw_text = re.sub(pat, "", raw_text, flags=re.IGNORECASE)

        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]
        clean_text = "\n\n".join(lines)

        return clean_text if len(clean_text) >= 50 else None


class DualTrackExtractor:
    """
    Dual-track Extractor combining RuleBasedExtractor (Priority 1)
    and HeuristicExtractor (Priority 2 Fallback).
    """
    def __init__(self, rules_dir: Optional[str] = None):
        self.rule_extractor = RuleBasedExtractor(rules_dir=rules_dir)
        self.heuristic_extractor = HeuristicExtractor()

    def extract_article_text(self, html_content: str, url: Optional[str] = None) -> str:
        """
        Extracts clean text using rule if available, else falls back to heuristic DOM analysis.
        """
        if url:
            rule_text = self.rule_extractor.extract_content(html_content, url=url)
            if rule_text and len(rule_text) >= 200:
                return rule_text

        # Fallback to heuristic extraction
        return self.heuristic_extractor.extract_article_text(html_content, url=url)
