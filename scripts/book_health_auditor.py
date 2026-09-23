"""
Novel Health Auditor & Self-Healing Repair Engine (CLI Entry).
Scans local novel TXT or EPUB files for quality defects:
- Truncated chapters (length < 300 words)
- Dictionary / lexicon definition pollution (e.g. 1.无；没有：)
- Paywall, VIP truncation, or WeChat cards (e.g. 微信扫码开通会员)
- Missing / discontinuous chapter sequences (e.g. jumps from 979 to 983)

Usage:
    python scripts/book_health_auditor.py <path_to_txt> [--fix]
"""

import argparse
import asyncio
import os
import sys

if sys.platform.startswith("win") and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.book_health_auditor import NovelHealthAuditor


def main():
    parser = argparse.ArgumentParser(description="Novel Quality Auditor & Self-Healing Repair Engine.")
    parser.add_argument("file", help="Path to local novel TXT or EPUB file")
    parser.add_argument("--fix", action="store_true", help="Auto-repair defective chapters from network")
    parser.add_argument("-s", "--source", help="Custom catalog URL for repair", default=None)
    parser.add_argument("-t", "--threshold", type=int, default=350, help="Minimum character length threshold (default: 350)")
    args = parser.parse_args()

    auditor = NovelHealthAuditor(min_char_threshold=args.threshold)
    if args.fix:
        asyncio.run(auditor.repair_file(args.file, source_url=args.source))
    else:
        defects, bname, author, _ = auditor.audit_file(args.file)
        print(f"📖 书名: 《{bname}》 (作者: {author})")
        if defects:
            print(f"⚠️ 发现 {len(defects)} 处缺陷章节:")
            for d in defects:
                print(f"  - [{d['type']}] 第 {d['chapter_num']} 章 ({d['title']}): {d['reason']}")
            print(f"\n💡 提示：运行 `python scripts/book_health_auditor.py \"{args.file}\" --fix` 即可一键自动修复！")
        else:
            print("✅ 全书 100% 完整，无任何断章、残缺或污染！")


if __name__ == "__main__":
    main()
