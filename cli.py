"""
Command Line Interface for Novel Latest Chapter Aggregator, Tracker, and Universal Extractor.
"""

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from typing import Optional, List, Dict, Tuple

if sys.platform.startswith("win") and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

from sources import SourceManager
from core.tracker import NovelTracker
from core.notifier import Notifier
from core.downloader import NovelDownloader
from core.universal_engine import UniversalNovelExtractor


def print_banner():
    banner = """
╔═════════════════════════════════════════════════════════════════╗
║            📚 全网小说最新章节聚合、监控与通用提取系统           ║
║            Universal Novel Tracker & Content Extractor          ║
╚═════════════════════════════════════════════════════════════════╝
    """
    print(banner)


async def cmd_search(novel_name: str):
    """Search for a novel across all sources and display results."""
    print(f"\n🔍 正在全网并发检索小说：《{novel_name}》...")
    start_time = time.time()
    
    manager = SourceManager()
    best_result, all_results = await manager.search_novel(novel_name)
    elapsed = time.time() - start_time
    
    if not all_results:
        print(f"\n❌ 未能找到《{novel_name}》的最新章节信息，请检查书名是否输入正确。")
        return

    print(f"✅ 检索完成 (耗时 {elapsed:.2f} 秒，共获取 {len(all_results)} 条来源数据)\n")
    
    print("┌" + "─" * 68 + "┐")
    print(f"│ 🏆 【全网最新章节推荐】")
    print(f"│ 📖 小说名称: 《{best_result.book_name}》 (作者: {best_result.author})")
    print(f"│ 🆕 最新章节: {best_result.latest_chapter_title}")
    print(f"│ 🌐 数据来源: {best_result.source_name}")
    print(f"│ ⏱️ 更新时间: {best_result.update_time}")
    if best_result.latest_chapter_url:
        print(f"│ 🔗 快速链接: {best_result.latest_chapter_url}")
    print("└" + "─" * 68 + "┘\n")

    if len(all_results) > 1:
        print("📑 各源站最新抓取详情对比：")
        print(f"{'序号':<4} {'数据源':<14} {'最新章节':<32} {'更新时间':<12}")
        print("-" * 68)
        for idx, res in enumerate(all_results, 1):
            title_display = res.latest_chapter_title
            if len(title_display) > 28:
                title_display = title_display[:27] + "…"
            print(f"[{idx:<2}] {res.source_name:<14} {title_display:<32} {res.update_time:<12}")
        print("-" * 68 + "\n")


async def cmd_follow(novel_name: str):
    """Search for novel and add it to watchlist."""
    print(f"\n➕ 正在检索并关注小说：《{novel_name}》...")
    manager = SourceManager()
    best, all_res = await manager.search_novel(novel_name)
    
    tracker = NovelTracker()
    if best:
        tracker.add_book(
            book_name=novel_name,
            author=best.author,
            latest_chapter=best.latest_chapter_title,
            latest_chapter_num=best.latest_chapter_num,
            latest_chapter_url=best.latest_chapter_url,
            source_name=best.source_name
        )
        print(f"🎉 关注成功！已将《{novel_name}》加入追更书架。")
        print(f"   当前记录章节: {best.latest_chapter_title} (来源: {best.source_name})")
    else:
        tracker.add_book(book_name=novel_name)
        print(f"⚠️ 暂未搜索到即时章节，已将《{novel_name}》加入书架，后续将自动监控。")


def cmd_unfollow(novel_name: str):
    """Remove novel from watchlist."""
    tracker = NovelTracker()
    if tracker.remove_book(novel_name):
        print(f"\n🗑️ 已将《{novel_name}》从追更书架移除。")
    else:
        print(f"\n❌ 书架中未找到《{novel_name}》。")


def cmd_list():
    """List all followed novels."""
    tracker = NovelTracker()
    books = tracker.get_all()
    
    print("\n📚 【追更书架列表】")
    if not books:
        print("  (书架空空如也，可以使用 `python cli.py follow <书名>` 添加小说)\n")
        return

    print("=" * 72)
    print(f"{'书名':<16} {'作者':<10} {'已知最新章节':<30} {'上次检查':<14}")
    print("-" * 72)
    for b in books:
        bname = f"《{b.get('book_name', '')}》"
        author = b.get('author', '未知')
        chapter = b.get('last_known_chapter', '暂无')
        if len(chapter) > 26:
            chapter = chapter[:25] + "…"
        checked = b.get('last_checked_at', '')
        if checked:
            checked = checked.split(" ")[-1]
        print(f"{bname:<16} {author:<10} {chapter:<30} {checked:<14}")
    print("=" * 72 + "\n")


async def cmd_check():
    """Check updates for all followed books."""
    tracker = NovelTracker()
    notifier = Notifier()
    books = tracker.get_all()
    
    if not books:
        print("\n书架中暂无追更小说，请先使用 `python cli.py follow <书名>` 添加。\n")
        return

    print(f"\n⚡ 开始检查书架更新 (共 {len(books)} 本小说)...")
    manager = SourceManager()
    
    update_count = 0
    for b in books:
        name = b["book_name"]
        print(f"🔎 正在检查: 《{name}》...")
        best, _ = await manager.search_novel(name)
        if best:
            is_new, old_title = tracker.check_and_update(
                book_name=name,
                new_chapter_title=best.latest_chapter_title,
                new_chapter_num=best.latest_chapter_num,
                new_chapter_url=best.latest_chapter_url,
                source_name=best.source_name
            )
            if is_new:
                update_count += 1
                notifier.notify_update(
                    book_name=name,
                    new_chapter=best.latest_chapter_title,
                    old_chapter=old_title,
                    chapter_url=best.latest_chapter_url,
                    source_name=best.source_name
                )
            else:
                print(f"  ✓ 《{name}》暂无更新 (当前: {best.latest_chapter_title})")
        else:
            print(f"  ⚠️ 《{name}》本次未检索到新数据")

    print(f"\n🏁 检查完成！共发现 {update_count} 本小说有更新。\n")


async def cmd_download(novel_name: str, url: Optional[str], start: int, limit: Optional[int], output: str, concurrency: int):
    """Download novel chapters."""
    downloader = NovelDownloader(output_dir=output, concurrency=concurrency)
    await downloader.download_novel(
        novel_name=novel_name,
        catalog_url=url,
        start_chapter=start,
        limit_chapters=limit
    )


async def cmd_extract(target: str, formats: str, start: int, limit: Optional[int], output: str, concurrency: int):
    """Extract novel from arbitrary URL or book title into TXT/EPUB/JSON."""
    format_list = [f.strip().lower() for f in formats.split(",") if f.strip()]
    extractor = UniversalNovelExtractor(output_dir=output, concurrency=concurrency)
    await extractor.extract(
        input_target=target,
        formats=format_list,
        start_chapter=start,
        limit_chapters=limit,
        custom_output_dir=output
    )


async def cmd_update_file(file_path: str, source: Optional[str], concurrency: int):
    """Incrementally update a local novel file."""
    from core.incremental_updater import IncrementalNovelUpdater
    updater = IncrementalNovelUpdater(concurrency=concurrency)
    await updater.update_book(file_path, custom_source_url=source)


async def cmd_audit(file_path: str, fix: bool, source: Optional[str], threshold: int):
    """Audit local novel file for quality defects and optionally auto-repair."""
    from core.book_health_auditor import NovelHealthAuditor
    auditor = NovelHealthAuditor(min_char_threshold=threshold)
    if fix:
        await auditor.repair_file(file_path, source_url=source)
    else:
        defects, bname, author, _ = auditor.audit_file(file_path)
        print(f"📖 书名: 《{bname}》 (作者: {author})")
        if defects:
            print(f"⚠️ 发现 {len(defects)} 处缺陷章节:")
            for d in defects:
                print(f"  - [{d['type']}] 第 {d['chapter_num']} 章 ({d['title']}): {d['reason']}")
            print(f"\n💡 提示：运行 `python cli.py audit \"{file_path}\" --fix` 即可一键自动修复！")
        else:
            print("✅ 全书 100% 完整，无任何断章、残缺或污染！")


async def cmd_monitor(interval_minutes: int):
    """Run continuous monitoring loop."""
    print(f"\n🔄 进入自动后台监控模式，每 {interval_minutes} 分钟检查一次更新...")
    print("按 Ctrl+C 可随时退出监控。\n")
    
    while True:
        try:
            print(f"\n⏰ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 触发定时更新检测...")
            await cmd_check()
            print(f"💤 休眠等待下次检查 ({interval_minutes} 分钟后)...")
            await asyncio.sleep(interval_minutes * 60)
        except (KeyboardInterrupt, asyncio.CancelledError):
            print("\n👋 已退出监控模式。")
            break
        except Exception as e:
            print(f"⚠️ 监控循环异常: {e}，将在 1 分钟后重试...")
            await asyncio.sleep(60)


def main():
    parser = argparse.ArgumentParser(
        description="全网小说最新章节聚合、监控与通用提取系统",
        formatter_class=argparse.RawTextHelpFormatter
    )
    subparsers = parser.add_subparsers(dest="command", help="支持的子命令")

    # search
    p_search = subparsers.add_parser("search", help="全网即时检索小说最新章节")
    p_search.add_argument("name", type=str, help="小说名称")

    # follow
    p_follow = subparsers.add_parser("follow", help="将小说添加到追更书架")
    p_follow.add_argument("name", type=str, help="小说名称")

    # unfollow
    p_unfollow = subparsers.add_parser("unfollow", help="从追更书架移除小说")
    p_unfollow.add_argument("name", type=str, help="小说名称")

    # list
    subparsers.add_parser("list", help="查看追更书架中的所有小说")

    # check
    subparsers.add_parser("check", help="立即检查书架所有小说的更新状态")

    # download
    p_download = subparsers.add_parser("download", help="下载小说章节到本地 TXT 文件")
    p_download.add_argument("name", type=str, help="小说名称")
    p_download.add_argument("-u", "--url", type=str, default=None, help="指定的目录/书籍页面 URL（可选）")
    p_download.add_argument("--start", type=int, default=1, help="起始章节序号，默认 1")
    p_download.add_argument("--limit", type=int, default=None, help="最多下载章节数（可选）")
    p_download.add_argument("-o", "--output", type=str, default="downloads", help="输出文件夹，默认 downloads")
    p_download.add_argument("-c", "--concurrency", type=int, default=8, help="并发下载数，默认 8")

    # extract (Universal Extractor)
    p_extract = subparsers.add_parser("extract", help="通用小说提取器：输入任意小说 URL（详情/目录/单章）或书名，一键导出 TXT/EPUB/JSON")
    p_extract.add_argument("target", type=str, help="任意小说相关 URL（详情页/目录页/单章阅读页）或小说名称")
    p_extract.add_argument("-f", "--format", type=str, default="txt,epub", help="导出格式，逗号分隔，如 txt,epub,json 或 all，默认 txt,epub")
    p_extract.add_argument("--start", type=int, default=1, help="起始章节序号，默认 1")
    p_extract.add_argument("--limit", type=int, default=None, help="最多提取章节数（可选）")
    p_extract.add_argument("-o", "--output", type=str, default="downloads", help="输出文件夹，默认 downloads")
    p_extract.add_argument("-c", "--concurrency", type=int, default=12, help="并发下载数，默认 12")

    # update-file (Incremental File Updater)
    p_update = subparsers.add_parser("update-file", aliases=["update"], help="本地小说文件智能增量续更：分析本地已有章节，仅抓取新章节追加并编译 EPUB")
    p_update.add_argument("file", type=str, help="本地小说文件路径（.txt 或 .epub）")
    p_update.add_argument("-s", "--source", type=str, default=None, help="指定的书源目录 URL（可选）")
    p_update.add_argument("-c", "--concurrency", type=int, default=15, help="并发抓取数，默认 15")

    # audit (Book Health Auditor)
    p_audit = subparsers.add_parser("audit", aliases=["check-file"], help="本地小说文件健康体检与自愈：扫描空章、断号、词典污染与 VIP 卡片并可一键自动修复")
    p_audit.add_argument("file", type=str, help="本地小说文件路径（.txt 或 .epub）")
    p_audit.add_argument("--fix", action="store_true", help="自动联网抓取优质镜像进行原地自愈修复")
    p_audit.add_argument("-s", "--source", type=str, default=None, help="指定的书源目录 URL（可选）")
    p_audit.add_argument("-t", "--threshold", type=int, default=350, help="章节字数过短下限阈值，默认 350")

    # relay (Browser Relay Server)
    p_relay = subparsers.add_parser("relay", help="启动本地浏览器接力服务，配合油猴脚本一键同步任何受盾保护小说")
    p_relay.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    p_relay.add_argument("-o", "--output", type=str, default="downloads", help="输出文件夹，默认 downloads")

    # web (Web Dashboard GUI)
    p_web = subparsers.add_parser("web", help="启动可视化 Web 控制台界面（一键提取、书架管理与文件下载）")
    p_web.add_argument("--port", type=int, default=5000, help="Web 监听端口，默认 5000")
    p_web.add_argument("--no-open", action="store_true", help="不自动打开默认浏览器")

    # monitor
    p_monitor = subparsers.add_parser("monitor", help="启动持续监控模式")
    p_monitor.add_argument("-i", "--interval", type=int, default=15, help="检查间隔（分钟），默认 15 分钟")

    args = parser.parse_args()

    if not args.command:
        print_banner()
        parser.print_help()
        return

    if args.command == "search":
        asyncio.run(cmd_search(args.name))
    elif args.command == "follow":
        asyncio.run(cmd_follow(args.name))
    elif args.command == "unfollow":
        cmd_unfollow(args.name)
    elif args.command == "list":
        cmd_list()
    elif args.command == "check":
        asyncio.run(cmd_check())
    elif args.command == "download":
        asyncio.run(cmd_download(args.name, args.url, args.start, args.limit, args.output, args.concurrency))
    elif args.command == "extract":
        asyncio.run(cmd_extract(args.target, args.format, args.start, args.limit, args.output, args.concurrency))
    elif args.command in ("update-file", "update"):
        asyncio.run(cmd_update_file(args.file, args.source, args.concurrency))
    elif args.command in ("audit", "check-file"):
        asyncio.run(cmd_audit(args.file, args.fix, args.source, args.threshold))
    elif args.command == "relay":
        from core.relay_server import RelayServer
        server = RelayServer(port=args.port, output_dir=args.output)
        server.start()
    elif args.command == "web":
        from core.web_server import WebApp
        app = WebApp(port=args.port)
        app.start(auto_open=not args.no_open)
    elif args.command == "monitor":
        asyncio.run(cmd_monitor(args.interval))


if __name__ == "__main__":
    main()
