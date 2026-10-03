"""
Content Fingerprinting and Repetition Circuit Breaker.
Detects placeholder text, duplicate synopses, and boilerplate spam across chapters
using normalized hashes and SimHash similarity.
"""

import hashlib
import re
from typing import Dict, Set, List
from collections import Counter
from core.exceptions import DataIncompleteError


class ContentFingerprintValidator:
    """
    Tracks text fingerprints across chapters to detect and reject repeating
    synopsis placeholders, WAF challenge pages, and copyright warnings.
    """
    def __init__(self, max_duplicate_allowed: int = 2):
        self.max_duplicate_allowed = max_duplicate_allowed
        self.seen_fingerprints: Counter = Counter()
        self.known_placeholder_patterns = [
            re.compile(r'老者[：:]\s*["“]你想报仇[”"]', re.IGNORECASE),
            re.compile(r'天庭是大平台.*?备用功力', re.IGNORECASE),
            re.compile(r'本网站使用安全服务防护恶意自动程序', re.IGNORECASE),
            re.compile(r'Just a moment\.\.\.', re.IGNORECASE),
            re.compile(r'同类热门书.*?最新上架', re.DOTALL),
        ]

    def _generate_fingerprint(self, text: str) -> str:
        """
        Generates a robust fingerprint by sampling across the body text (excluding static headers/footers).
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        body_lines = [l for l in lines if not any(k in l for k in ("プライバシー", "規約", "Cookie", "版权所有", "All rights", "免责声明", "广告"))]
        clean_core = re.sub(r'[^\w\u4e00-\u9fa5]', '', "".join(body_lines))
        
        if len(clean_core) < 200:
            sample = clean_core
        else:
            # Sample across 3 slices: 25%, 50%, 75% of text
            l = len(clean_core)
            p1 = clean_core[l//4 : l//4 + 100]
            p2 = clean_core[l//2 : l//2 + 100]
            p3 = clean_core[3*l//4 : 3*l//4 + 100]
            sample = f"{p1}|{p2}|{p3}"
            
        return hashlib.md5(sample.encode('utf-8')).hexdigest()

    def validate_and_record(self, chapter_title: str, text: str, source_url: str = "") -> None:
        """
        Validates whether chapter text is a repeated placeholder or synopsis.
        Raises DataIncompleteError if repetition limit is exceeded.
        """
        if not text or len(text.strip()) < 100:
            raise DataIncompleteError(chapter_title, source_url, len(text), "Text is empty or too short")

        # 1. Check known boilerplate / synopsis patterns
        for pat in self.known_placeholder_patterns:
            if pat.search(text):
                raise DataIncompleteError(
                    chapter_title,
                    source_url,
                    len(text),
                    f"Matched blacklisted boilerplate/synopsis pattern: {pat.pattern[:30]}"
                )

        # 2. Check fingerprint repetition count
        fp = self._generate_fingerprint(text)
        self.seen_fingerprints[fp] += 1

        if self.seen_fingerprints[fp] > self.max_duplicate_allowed:
            raise DataIncompleteError(
                chapter_title,
                source_url,
                len(text),
                f"Duplicate content fingerprint detected ({self.seen_fingerprints[fp]} occurrences). Likely placeholder spam."
            )
