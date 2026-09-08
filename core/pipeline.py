"""
Regex Cleaning Pipeline for novel text standardization.
Processes raw scraped chapter text through multi-stage filters to produce clean, well-formatted paragraphs.
Includes component-level sidebar stripping and content fingerprint repetition circuit breaking.
"""

import re
from typing import List, Optional, Tuple
from core.exceptions import DataIncompleteError
from core.content_fingerprint import ContentFingerprintValidator


# Common novel site noise & ad patterns
NOISE_PATTERNS = [
    re.compile(r'请记住本书首发域名[：:\s]*[a-zA-Z0-9\.\/]+', re.IGNORECASE),
    re.compile(r'最新章节更新[：:\s]*[a-zA-Z0-9\.\/]+', re.IGNORECASE),
    re.compile(r'天才一秒记住.*?[网站|域名]', re.IGNORECASE),
    re.compile(r'(?:手机版|移动端|手机用户请)?(?:访问|阅读|浏览)[：:\s]*[a-zA-Z0-9\.\/]+', re.IGNORECASE),
    re.compile(r'点击下一页继续阅读.*', re.IGNORECASE),
    re.compile(r'[\(（]?\s*本章完\s*[\)）]?', re.IGNORECASE),
    re.compile(r'[\(（]?\s*未完待续\s*[\)）]?', re.IGNORECASE),
    re.compile(r'https?://[^\s<>"]+', re.IGNORECASE),
    re.compile(r'(?:www\.)?[a-zA-Z0-9\-]+\.(?:com|net|org|cc|la|tv|biz|me|tw|hk|info|co)(?:/[^\s<>"]*)?', re.IGNORECASE),
    re.compile(r'^(?:笔趣阁|顶点小说|飘天文学|69书吧|51read|番茄小说|起点中文网|创世中文网|飞卢小说).*$', re.MULTILINE),
    re.compile(r'^\s*[-=_]{3,}\s*$', re.MULTILINE),
]

# Structural Component Blacklist (Sidebar, recommendations, book meta)
SIDEBAR_COMPONENT_PATTERNS = [
    re.compile(r'^(?:同类热门书|同类书籍最近更新|最新上架|相关推荐|热评讨论|版权信息|作家主页|更多推荐|书籍简介|版权信息).*$', re.IGNORECASE),
    re.compile(r'^(?:更新时间[：:]|最新章节[：:]|热度[：:]|版权[：:]|品牌[：:]|开会员|打开QQ免费看).*$', re.IGNORECASE),
    re.compile(r'^\d+(\.\d+)?万字\s*[\|\-—]\s*(?:连载|完结).*$', re.IGNORECASE),
    re.compile(r'^.*(?:仙侠|都市|玄幻|武侠|历史|科幻|网游)(?:连载|完结)\d+(\.\d+)?万字.*$', re.IGNORECASE),
    re.compile(r'^更新至[：:].*$', re.IGNORECASE),
    re.compile(r'^展开\s+.*$', re.IGNORECASE),
    re.compile(r'^.*?(?:小说推荐阅读|小说推荐|热门推荐)[：:].*$', re.IGNORECASE),
    re.compile(r'^-\s*(?:免费|会员).*$', re.IGNORECASE),
    re.compile(r'^本书数字版权由.*?制作发行.*$', re.IGNORECASE),
]

# Patterns for author notes / promos that should be filtered if standalone lines
STANDALONE_PROMO_PATTERNS = [
    re.compile(r'^(?:求[月推荐点追收订精]+[票读藏阅品]?|打赏|加更|盟主|[!！。~～\s，,]|感谢)+$'),
    re.compile(r'^(?:书友群|官方群|交流群|QQ群|读者群)[：:\s]*\d+'),
    re.compile(r'^感谢.*?打赏.*?$'),
    re.compile(r'^感谢.*?盟主.*?$'),
    re.compile(r'^感谢.*?送.*?$'),
]

# Truncation markers for preview detection
TRUNCATION_MARKERS = [
    re.compile(r'\.{3,}$'),
    re.compile(r'……$'),
    re.compile(r'（未完）$'),
    re.compile(r'\(待续\)$'),
    re.compile(r'【剩余字数.*?请前往.*?阅读】'),
]


class RegexCleaningPipeline:
    def __init__(self, min_char_length: int = 400, validator: Optional[ContentFingerprintValidator] = None):
        self.min_char_length = min_char_length
        self.validator = validator or ContentFingerprintValidator()

    def clean_text(self, raw_text: str, chapter_title: str = "", source_url: str = "") -> str:
        """
        Runs raw chapter text through the cleaning pipeline and formats standard paragraphs.
        Raises DataIncompleteError if the cleaned text length is below the minimum threshold or fingerprint repeats.
        """
        if not raw_text:
            raise DataIncompleteError(chapter_title, source_url, 0, "Empty content returned")

        # Stage 1: Global pattern removal
        text = raw_text
        for pattern in NOISE_PATTERNS:
            text = pattern.sub('', text)

        # Stage 2: Line-by-line filtering & component stripping
        lines = text.split('\n')
        cleaned_paragraphs: List[str] = []
        skip_remaining_section = False

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            # Check sidebar / recommendation section start
            if any(p.match(line_str) for p in SIDEBAR_COMPONENT_PATTERNS):
                # If we encounter recommendations or metadata headers, filter the line
                continue

            # Skip redundant chapter title at top of body
            if chapter_title and (line_str == chapter_title or line_str in chapter_title):
                continue
            if re.match(r'^第\s*[0-9零一二两三四五六七八九十百千万]+\s*[章节回集卷篇节]\b', line_str) and len(line_str) < 30:
                continue

            # Skip standalone promos
            if any(p.match(line_str) for p in STANDALONE_PROMO_PATTERNS):
                continue

            cleaned_paragraphs.append(line_str)

        # Re-assemble body text
        clean_body = "\n\n".join("    " + p for p in cleaned_paragraphs)
        char_count = sum(len(p) for p in cleaned_paragraphs)

        # Stage 3: Fingerprinting & Anomaly Detection
        self.validator.validate_and_record(chapter_title, clean_body, source_url)

        if char_count < self.min_char_length:
            raise DataIncompleteError(
                chapter_title=chapter_title,
                url=source_url,
                content_length=char_count,
                reason=f"Character count ({char_count}) is below minimum threshold ({self.min_char_length})"
            )

        # Check for trailing preview truncation markers
        if cleaned_paragraphs:
            last_p = cleaned_paragraphs[-1]
            if char_count < 1000 and any(m.search(last_p) for m in TRUNCATION_MARKERS):
                raise DataIncompleteError(
                    chapter_title=chapter_title,
                    url=source_url,
                    content_length=char_count,
                    reason="Trailing preview truncation marker detected"
                )

        return clean_body
