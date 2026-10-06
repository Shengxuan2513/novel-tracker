"""
Web Dashboard and Visual GUI for NovelTracker 2.0.
Provides an interactive, modern Web UI for novel search, universal extraction,
bookshelf management, real-time progress monitoring, and EPUB/TXT downloads.
"""

import asyncio
import json
import os
import urllib.parse
from datetime import datetime
from aiohttp import web

from core.tracker import NovelTracker
from sources.manager import SourceManager
from core.notifier import Notifier
from core.universal_engine import UniversalNovelExtractor
from core.source_cache import SourceCache
from core.heuristic_catalog import HeuristicCatalogExtractor
from core.official_probe import OfficialProgressProber


HTML_DASHBOARD = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NovelTracker 2.0 - 全网小说聚合监控与通用提取系统</title>
    <link href="https://cdn.jsdelivr.net/npm/font-awesome@4.7.0/css/font-awesome.min.css" rel="stylesheet">
    <style>
        :root {
            --bg: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.7);
            --border: rgba(255, 255, 255, 0.1);
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --accent: #8b5cf6;
            --success: #10b981;
            --danger: #ef4444;
            --warning: #f59e0b;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            background: var(--bg);
            background-image: 
                radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.15) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(139, 92, 246, 0.15) 0px, transparent 50%);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }

        /* Top Navigation Bar */
        .navbar {
            background: rgba(15, 23, 42, 0.85);
            backdrop-filter: blur(12px);
            border-bottom: 1px solid var(--border);
            padding: 16px 32px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .brand {
            font-size: 20px;
            font-weight: 700;
            background: linear-gradient(135deg, #60a5fa, #c084fc);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .nav-tabs {
            display: flex;
            gap: 8px;
        }

        .nav-tab {
            padding: 8px 16px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 500;
            color: var(--text-muted);
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .nav-tab:hover {
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.05);
        }

        .nav-tab.active {
            color: #fff;
            background: var(--primary);
        }

        /* Container Layout */
        .container {
            max-width: 1200px;
            margin: 32px auto;
            padding: 0 24px;
            width: 100%;
            flex: 1;
        }

        .tab-content {
            display: none;
        }

        .tab-content.active {
            display: block;
            animation: fadeIn 0.3s ease-in-out;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* Card Elements */
        .card {
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
        }

        .card-title {
            font-size: 18px;
            font-weight: 600;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Inputs and Buttons */
        .form-group {
            margin-bottom: 16px;
        }

        .form-label {
            display: block;
            font-size: 13px;
            font-weight: 500;
            color: var(--text-muted);
            margin-bottom: 6px;
        }

        .input-group {
            display: flex;
            gap: 8px;
        }

        .form-control {
            flex: 1;
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border);
            border-radius: 8px;
            padding: 10px 14px;
            color: #fff;
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
        }

        .form-control:focus {
            border-color: var(--primary);
        }

        .btn {
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            border: none;
            cursor: pointer;
            transition: all 0.2s;
            display: inline-flex;
            align-items: center;
            gap: 6px;
        }

        .btn-primary {
            background: var(--primary);
            color: #fff;
        }

        .btn-primary:hover {
            background: var(--primary-hover);
        }

        .btn-secondary {
            background: rgba(255, 255, 255, 0.1);
            color: #fff;
        }

        .btn-secondary:hover {
            background: rgba(255, 255, 255, 0.15);
        }

        .btn-danger {
            background: rgba(239, 68, 68, 0.2);
            color: #f87171;
            border: 1px solid rgba(239, 68, 68, 0.3);
        }

        .btn-danger:hover {
            background: rgba(239, 68, 68, 0.3);
        }

        .btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Checkbox & Options */
        .checkbox-group {
            display: flex;
            gap: 16px;
            margin-bottom: 16px;
        }

        .checkbox-label {
            font-size: 13px;
            color: #cbd5e1;
            display: flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
        }

        /* Terminal Logs Output */
        .log-terminal {
            background: #090d16;
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 12px;
            padding: 16px;
            font-family: "Cascadia Code", "Fira Code", Consolas, Courier, monospace;
            font-size: 12px;
            line-height: 1.6;
            color: #38bdf8;
            max-height: 380px;
            overflow-y: auto;
            white-space: pre-wrap;
            word-break: break-all;
        }

        /* Bookshelf Grid */
        .book-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 16px;
        }

        .book-card {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            transition: all 0.2s;
        }

        .book-card:hover {
            border-color: rgba(255, 255, 255, 0.25);
            transform: translateY(-2px);
        }

        .book-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 8px;
        }

        .book-name {
            font-size: 16px;
            font-weight: 600;
            color: #fff;
        }

        .book-meta {
            font-size: 12px;
            color: var(--text-muted);
            margin-bottom: 12px;
            line-height: 1.5;
        }

        .book-actions {
            display: flex;
            gap: 8px;
            margin-top: auto;
        }

        /* File List Table */
        .table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }

        .table th, .table td {
            padding: 12px 16px;
            text-align: left;
            border-bottom: 1px solid var(--border);
        }

        .table th {
            color: var(--text-muted);
            font-weight: 600;
        }

        .table tr:hover td {
            background: rgba(255, 255, 255, 0.02);
        }

        .badge {
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
        }

        .badge-epub { background: rgba(139, 92, 246, 0.2); color: #c084fc; border: 1px solid rgba(139, 92, 246, 0.3); }
        .badge-txt { background: rgba(59, 130, 246, 0.2); color: #60a5fa; border: 1px solid rgba(59, 130, 246, 0.3); }
        .badge-json { background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.3); }

        /* Toast */
        #toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background: #1e293b;
            color: #fff;
            padding: 12px 20px;
            border-radius: 10px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.5);
            display: none;
            border: 1px solid var(--border);
            z-index: 1000;
        }
    </style>
</head>
<body>

    <!-- Navbar -->
    <div class="navbar">
        <div class="brand">
            <i class="fa fa-book"></i> NovelTracker 2.0
        </div>
        <div class="nav-tabs">
            <div class="nav-tab active" onclick="switchTab('tab-extract')"><i class="fa fa-cloud-download"></i> 通用提取器</div>
            <div class="nav-tab" onclick="switchTab('tab-bookshelf')"><i class="fa fa-bookmark"></i> 追更书架</div>
            <div class="nav-tab" onclick="switchTab('tab-files')"><i class="fa fa-folder-open"></i> 文件下载中心</div>
            <div class="nav-tab" onclick="switchTab('tab-legado')"><i class="fa fa-mobile"></i> 阅读 3.0 联动</div>
            <div class="nav-tab" onclick="switchTab('tab-relay')"><i class="fa fa-shield"></i> 浏览器接力抗盾</div>
        </div>
    </div>

    <!-- Main Container -->
    <div class="container">

        <!-- Tab 1: Universal Extractor -->
        <div id="tab-extract" class="tab-content active">
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fa fa-magic"></i> 全网零规则小说提取器</div>
                    <span style="font-size: 12px; color: var(--text-muted);">支持书名、目录页、详情页或单章阅读页</span>
                </div>
                <div class="form-group">
                    <label class="form-label">输入小说名称或网页 URL：</label>
                    <div class="input-group">
                        <input type="text" id="extract-target" class="form-control" placeholder="例如：宿命之环 或 https://www.bige3.cc/book/123/">
                        <button class="btn btn-primary" id="btn-start-extract" onclick="startExtract()"><i class="fa fa-play"></i> 开始提取</button>
                    </div>
                </div>
                <div class="checkbox-group">
                    <label class="checkbox-label"><input type="checkbox" id="fmt-epub" checked> 导出标准 EPUB3 电子书</label>
                    <label class="checkbox-label"><input type="checkbox" id="fmt-txt" checked> 导出排版 TXT 纯文本</label>
                    <label class="checkbox-label"><input type="checkbox" id="fmt-json"> 导出结构化 JSON</label>
                </div>
                <div class="input-group" style="margin-bottom: 12px;">
                    <div style="flex: 1;">
                        <label class="form-label">起始章节序号（可选）：</label>
                        <input type="number" id="extract-start" class="form-control" value="1" min="1">
                    </div>
                    <div style="flex: 1;">
                        <label class="form-label">最大提取章节数（可选）：</label>
                        <input type="number" id="extract-limit" class="form-control" placeholder="默认全本">
                    </div>
                </div>
            </div>

            <!-- Terminal Realtime Logs -->
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fa fa-terminal"></i> 提取过程实时终端回显</div>
                    <button class="btn btn-secondary" style="padding: 4px 10px; font-size: 12px;" onclick="clearLogs()"><i class="fa fa-trash"></i> 清屏</button>
                </div>
                <div id="log-box" class="log-terminal">等待输入任务中...</div>
            </div>
        </div>

        <!-- Tab 2: Bookshelf -->
        <div id="tab-bookshelf" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fa fa-bookmark"></i> 追更书架列表</div>
                    <button class="btn btn-primary" onclick="checkAllUpdates()"><i class="fa fa-refresh"></i> 一键检查更新</button>
                </div>
                <div class="input-group" style="margin-bottom: 20px;">
                    <input type="text" id="follow-name" class="form-control" placeholder="输入要添加追更的小说名称..">
                    <button class="btn btn-primary" onclick="addFollowBook()"><i class="fa fa-plus"></i> 添加追更</button>
                </div>
                <div id="bookshelf-list" class="book-grid">
                    <!-- Dynamic Bookshelf Cards -->
                </div>
            </div>
        </div>

        <!-- Tab 3: Files -->
        <div id="tab-files" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fa fa-download"></i> 已生成文件库</div>
                    <button class="btn btn-primary" onclick="loadFiles()"><i class="fa fa-refresh"></i> 刷新列表</button>
                </div>
                <table class="table">
                    <thead>
                        <tr>
                            <th>文件名</th>
                            <th>格式</th>
                            <th>文件大小</th>
                            <th>生成时间</th>
                            <th>操作</th>
                        </tr>
                    </thead>
                    <tbody id="files-table-body">
                        <tr><td colspan="5" style="text-align: center; color: var(--text-muted);">正在扫描 downloads 目录...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Tab Legado: Legado Integration -->
        <div id="tab-legado" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fa fa-mobile"></i> 阅读 3.0 (Legado) 深度联动</div>
                    <span style="font-size: 12px; color: var(--text-muted);">局域网无线推书 / 优质书源直导 / APK 安装</span>
                </div>
                <div style="font-size: 14px; line-height: 1.8; color: #cbd5e1;">
                    <p>通过 NovelTracker 与开源神器<strong>「阅读 3.0 (Legado)」</strong>深度融合，无需数据线即可实现全自动无线同步与移动端畅读：</p>

                    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin: 20px 0;">
                        <!-- Feature 1: OPDS -->
                        <div style="background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border); border-radius: 12px; padding: 18px;">
                            <div style="font-weight: 600; color: #60a5fa; margin-bottom: 8px; font-size: 15px;">
                                <i class="fa fa-book"></i> 1. OPDS 无线书库 (随下随看)
                            </div>
                            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
                                将 downloads 目录下的全部精校 EPUB/TXT 转换为标准 OPDS 书库。手机连入同一 Wi-Fi 即可无线下载。
                            </p>
                            <div class="input-group">
                                <input type="text" id="legado-opds-url" class="form-control" readonly style="font-size: 12px; background: rgba(0,0,0,0.4);">
                                <button class="btn btn-primary" onclick="copyToClipboard('legado-opds-url')"><i class="fa fa-copy"></i> 复制</button>
                            </div>
                            <div style="margin-top: 10px; font-size: 12px; color: #94a3b8;">
                                <strong>使用方法</strong>: 打开阅读 App ➜ 「书架」右上角菜单 ➜ 「添加外部书库 / WebDAV」➜ 填入上方 URL。
                            </div>
                        </div>

                        <!-- Feature 2: BookSource -->
                        <div style="background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border); border-radius: 12px; padding: 18px;">
                            <div style="font-weight: 600; color: #c084fc; margin-bottom: 8px; font-size: 15px;">
                                <i class="fa fa-code-fork"></i> 2. 精校书源一键网络导入
                            </div>
                            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
                                经过 NovelTracker 验证的高可用免防爬书源规则（支持多页章节自动拼接与正文纯净化）。
                            </p>
                            <div class="input-group">
                                <input type="text" id="legado-sources-url" class="form-control" readonly style="font-size: 12px; background: rgba(0,0,0,0.4);">
                                <button class="btn btn-primary" onclick="copyToClipboard('legado-sources-url')"><i class="fa fa-copy"></i> 复制</button>
                            </div>
                            <div style="margin-top: 10px; font-size: 12px; color: #94a3b8;">
                                <strong>使用方法</strong>: 打开阅读 App ➜ 「我的」➜ 「书源管理」➜ 右上角菜单 ➜ 「网络导入」➜ 粘贴上方 URL。
                            </div>
                        </div>

                        <!-- Feature 3: APK Direct Download -->
                        <div style="background: rgba(15, 23, 42, 0.6); border: 1px solid var(--border); border-radius: 12px; padding: 18px;">
                            <div style="font-weight: 600; color: #34d399; margin-bottom: 8px; font-size: 15px;">
                                <i class="fa fa-android"></i> 3. 手机客户端直接获取
                            </div>
                            <p style="font-size: 13px; color: var(--text-muted); margin-bottom: 12px;">
                                针对已识别的 Mate 30E Pro 5G (Kirin 990E / 64位 ARM) 精准匹配的官方纯净无广告安装包。
                            </p>
                            <div style="display: flex; gap: 10px; align-items: center;">
                                <a id="legado-apk-download-btn" href="/legado.apk" class="btn btn-primary" style="flex: 1; text-align: center; text-decoration: none;" download>
                                    <i class="fa fa-download"></i> 下载 Legado 3.26 APK (9.8 MB)
                                </a>
                                <button class="btn btn-secondary" onclick="copyToClipboard('legado-apk-url')"><i class="fa fa-link"></i> 复制下载链接</button>
                            </div>
                            <input type="hidden" id="legado-apk-url">
                            <div style="margin-top: 10px; font-size: 12px; color: #94a3b8;">
                                <strong>华为手机提示</strong>: 安装时如提示“外部来源应用”，点击“继续安装”或“解除管控”即可，100% 官方开源安全。
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Tab 4: Relay & Anti-WAF -->
        <div id="tab-relay" class="tab-content">
            <div class="card">
                <div class="card-header">
                    <div class="card-title"><i class="fa fa-shield"></i> 浏览器接力抗盾配置指南</div>
                </div>
                <div style="font-size: 14px; line-height: 1.8; color: #cbd5e1;">
                    <p>遇到同时开启了 <strong>Cloudflare 5秒行为盾 (Turnstile)</strong> 或 <strong>VIP 付费验证</strong> 的极端小说站点时，可通过以下 3 步实现 100% 穿透：</p>
                    <ol style="margin: 16px 0 16px 24px;">
                        <li>确保在终端中运行接力服务：<code>python cli.py relay</code>（默认监听 <code>127.0.0.1:8765</code>）。</li>
                        <li>在 Chrome / Edge 浏览器中安装油猴插件，并添加脚本：<a href="/scripts/novel_relay.user.js" target="_blank" style="color: var(--primary);">scripts/novel_relay.user.js</a>。</li>
                        <li>在真实浏览器中正常打开小说阅读页，点击页面右下角的 <strong>“⚡ 一键同步本章”</strong> 即可毫秒级无损保存！</li>
                    </ol>
                </div>
            </div>
        </div>

    </div>

    <!-- Toast Notification -->
    <div id="toast"></div>

    <script>
        function showToast(msg) {
            const t = document.getElementById('toast');
            t.innerText = msg;
            t.style.display = 'block';
            setTimeout(() => { t.style.display = 'none'; }, 3000);
        }

        function switchTab(tabId) {
            document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.nav-tab').forEach(el => el.classList.remove('active'));
            document.getElementById(tabId).classList.add('active');
            event.currentTarget.classList.add('active');

            if (tabId === 'tab-bookshelf') loadBookshelf();
            if (tabId === 'tab-files') loadFiles();
            if (tabId === 'tab-legado') loadLegadoInfo();
        }

        // Start Universal Extraction
        async function startExtract() {
            const target = document.getElementById('extract-target').value.trim();
            if (!target) {
                showToast('请输入小说名称或网址！');
                return;
            }

            const formats = [];
            if (document.getElementById('fmt-epub').checked) formats.push('epub');
            if (document.getElementById('fmt-txt').checked) formats.push('txt');
            if (document.getElementById('fmt-json').checked) formats.push('json');

            const start = parseInt(document.getElementById('extract-start').value) || 1;
            const limitVal = document.getElementById('extract-limit').value.trim();
            const limit = limitVal ? parseInt(limitVal) : null;

            const logBox = document.getElementById('log-box');
            logBox.innerText = '正在建立实时连接...\n';

            const btn = document.getElementById('btn-start-extract');
            btn.disabled = true;

            try {
                const response = await fetch('/api/extract', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        target: target,
                        formats: formats,
                        start: start,
                        limit: limit
                    })
                });

                const reader = response.body.getReader();
                const decoder = new TextDecoder('utf-8');

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    const chunk = decoder.decode(value, { stream: true });
                    logBox.innerText += chunk;
                    logBox.scrollTop = logBox.scrollHeight;
                }
            } catch (err) {
                logBox.innerText += `\n❌ 请求发生异常: ${err}\n`;
            } finally {
                btn.disabled = false;
            }
        }

        // Load Bookshelf
        async function loadBookshelf() {
            const container = document.getElementById('bookshelf-list');
            container.innerHTML = '<div style="color: var(--text-muted); font-size: 13px;">正在加载书架...</div>';
            try {
                const res = await fetch('/api/bookshelf');
                if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
                const data = await res.json();
                if (!data.books || data.books.length === 0) {
                    container.innerHTML = '<div style="color: var(--text-muted); font-size: 13px;">书架空空如也，快在上方添加一本吧！</div>';
                    return;
                }
                container.innerHTML = data.books.map(b => {
                    let gapBadge = '';
                    if (b.gap_chapters === 0) {
                        gapBadge = '<span class="badge" style="background: rgba(16, 185, 129, 0.2); color: #34d399; border: 1px solid rgba(16, 185, 129, 0.4);"><i class="fa fa-check-circle"></i> 已与官方同步</span>';
                    } else if (b.gap_chapters > 0) {
                        gapBadge = `<span class="badge" style="background: rgba(249, 115, 22, 0.2); color: #fb923c; border: 1px solid rgba(249, 115, 22, 0.4);"><i class="fa fa-clock-o"></i> 开放源落后 ${b.gap_chapters} 章 (VIP连载中)</span>`;
                    }
                    return `
                        <div class="book-card">
                            <div class="book-header">
                                <div class="book-name">《${b.name}》 <span style="font-size: 12px; color: var(--text-muted); font-weight: normal;">作者: ${b.author || '未知'}</span></div>
                                <button class="btn btn-danger" style="padding: 3px 8px; font-size: 11px;" onclick="removeFollow('${b.name}')">移除</button>
                            </div>
                            <div class="book-meta">
                                <div style="margin-bottom: 6px; background: rgba(0,0,0,0.25); padding: 8px 10px; border-radius: 8px;">
                                    <div style="font-size: 11px; color: #fbbf24; margin-bottom: 2px;"><i class="fa fa-star"></i> <strong>官方正版最新:</strong></div>
                                    <div style="font-size: 13px; color: #fef08a; font-weight: 600;">${b.official_chapter || '同步中...'}</div>
                                    <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">来源: ${b.official_source || '官方平台'}</div>
                                </div>
                                <div style="margin-bottom: 6px; background: rgba(0,0,0,0.25); padding: 8px 10px; border-radius: 8px;">
                                    <div style="font-size: 11px; color: #60a5fa; margin-bottom: 2px;"><i class="fa fa-download"></i> <strong>开放书源可下载:</strong></div>
                                    <div style="font-size: 13px; color: #93c5fd; font-weight: 600;">${b.crawlable_chapter || b.last_known_chapter_title || '暂无数据'}</div>
                                    <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">来源: ${b.crawlable_source || b.source_name || '全网聚合'}</div>
                                </div>
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 6px;">
                                    <div>${gapBadge}</div>
                                    <div style="font-size: 11px; color: var(--text-muted);">${b.last_checked || '尚未检查'}</div>
                                </div>
                            </div>
                            <div class="book-actions" style="margin-top: 10px; display: flex; gap: 8px;">
                                <button class="btn btn-primary" style="padding: 6px 12px; font-size: 12px; flex: 1;" onclick="extractDirectly('${b.name}')"><i class="fa fa-download"></i> 导出全本</button>
                                <button class="btn btn-secondary" style="padding: 6px 10px; font-size: 12px;" onclick="switchTab('tab-relay')"><i class="fa fa-shield"></i> 抗盾接力</button>
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (err) {
                container.innerHTML = `<div style="color: var(--danger); font-size: 13px;">加载失败: ${err}</div>`;
            }
        }

        async function addFollowBook() {
            const name = document.getElementById('follow-name').value.trim();
            if (!name) return showToast('请输入小说名称！');
            await fetch('/api/bookshelf/add', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name })
            });
            document.getElementById('follow-name').value = '';
            showToast(`已添加《${name}》到书架！`);
            loadBookshelf();
        }

        async function removeFollow(name) {
            if (!confirm(`确认将《${name}》从书架移除吗？`)) return;
            await fetch('/api/bookshelf/remove', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: name })
            });
            showToast(`已移除《${name}》`);
            loadBookshelf();
        }

        async function checkAllUpdates() {
            showToast('正在全网多源检查书架更新...');
            await fetch('/api/bookshelf/check', { method: 'POST' });
            showToast('检查完成！');
            loadBookshelf();
        }

        function extractDirectly(name) {
            document.getElementById('extract-target').value = name;
            switchTab('tab-extract');
            startExtract();
        }

        // Load Files
        async function loadFiles() {
            const tbody = document.getElementById('files-table-body');
            tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">正在扫描 downloads 目录...</td></tr>';
            try {
                const res = await fetch('/api/files');
                const data = await res.json();
                if (!data.files || data.files.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--text-muted);">暂无下载文件</td></tr>';
                    return;
                }
                tbody.innerHTML = data.files.map(f => {
                    let badgeClass = 'badge-txt';
                    if (f.ext === 'epub') badgeClass = 'badge-epub';
                    if (f.ext === 'json') badgeClass = 'badge-json';
                    return `
                        <tr>
                            <td><strong>${f.name}</strong></td>
                            <td><span class="badge ${badgeClass}">${f.ext.toUpperCase()}</span></td>
                            <td>${f.size_formatted}</td>
                            <td style="color: var(--text-muted);">${f.modified}</td>
                            <td>
                                <a href="/api/download/${encodeURIComponent(f.name)}" class="btn btn-primary" style="padding: 4px 10px; font-size: 11px;" download><i class="fa fa-download"></i> 下载</a>
                            </td>
                        </tr>
                    `;
                }).join('');
            } catch (err) {
                tbody.innerHTML = `<tr><td colspan="5" style="color: var(--danger);">加载失败: ${err}</td></tr>`;
            }
        }

        // Legado Info & Copy
        async function loadLegadoInfo() {
            try {
                const res = await fetch('/api/legado/info');
                const data = await res.json();
                document.getElementById('legado-opds-url').value = data.opds_url;
                document.getElementById('legado-sources-url').value = data.sources_url;
                document.getElementById('legado-apk-url').value = data.apk_url;
            } catch (err) {
                console.error('Failed to load legado info:', err);
            }
        }

        function copyToClipboard(elementId) {
            const el = document.getElementById(elementId);
            if (!el) return;
            el.select();
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(el.value).then(() => {
                    showToast('已成功复制链接到剪贴板！');
                }).catch(() => {
                    document.execCommand('copy');
                    showToast('已成功复制链接到剪贴板！');
                });
            } else {
                document.execCommand('copy');
                showToast('已成功复制链接到剪贴板！');
            }
        }

        // Initial preload
        window.addEventListener('DOMContentLoaded', () => {
            loadLegadoInfo();
        });
    </script>
</body>
</html>
"""


class WebApp:
    def __init__(self, host: str = "127.0.0.1", port: int = 5000, output_dir: str = "downloads"):
        self.host = host
        self.port = port
        self.output_dir = output_dir
        self.tracker = NovelTracker()
        self.sources_manager = SourceManager()
        self.source_cache = SourceCache()
        self.catalog_extractor = HeuristicCatalogExtractor()
        self.official_prober = OfficialProgressProber()
        self.notifier = Notifier()
        os.makedirs(self.output_dir, exist_ok=True)

    async def handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=HTML_DASHBOARD, content_type="text/html", charset="utf-8")

    async def handle_get_bookshelf(self, request: web.Request) -> web.Response:
        books = self.tracker.get_all()
        formatted_books = []
        for b in books:
            formatted_books.append({
                "name": b.get("book_name", ""),
                "author": b.get("author", "未知"),
                "official_chapter": b.get("official_chapter", b.get("last_known_chapter", "暂无数据")),
                "official_source": b.get("official_source", "官方首发站"),
                "official_url": b.get("official_url", ""),
                "official_time": b.get("official_time", "正版连载中"),
                "crawlable_chapter": b.get("crawlable_chapter", b.get("last_known_chapter", "暂无数据")),
                "crawlable_source": b.get("crawlable_source", b.get("source_name", "全网聚合")),
                "last_known_chapter_title": b.get("last_known_chapter", "暂无数据"),
                "source_name": b.get("source_name", "全网聚合"),
                "gap_chapters": b.get("gap_chapters", 0),
                "last_checked": b.get("last_checked_at", "尚未检查")
            })
        return web.json_response({"books": formatted_books})

    async def handle_add_bookshelf(self, request: web.Request) -> web.Response:
        data = await request.json()
        name = data.get("name", "").strip()
        if name:
            # 1. Concurrent official probe
            off_task = asyncio.create_task(self.official_prober.probe(name))

            # 2. Probe crawlable source
            author = "未知"
            c_chap = ""
            c_num = 0.0
            c_url = ""
            c_src = "全网聚合"
            cat_url = ""

            cached = self.source_cache.get(name)
            if cached and cached.get("catalog_url"):
                try:
                    meta, chaps = await self.catalog_extractor.discover_catalog(cached["catalog_url"])
                    if chaps:
                        last_chap = chaps[-1]
                        author = meta.get("author", cached.get("author", "未知"))
                        c_chap = last_chap[1]
                        c_num = last_chap[3]
                        c_url = last_chap[2]
                        c_src = cached.get("source_name", "全网聚合")
                        cat_url = cached["catalog_url"]
                except Exception:
                    pass

            if not c_chap:
                best, _ = await self.sources_manager.search_novel(name)
                if best:
                    author = best.author
                    c_chap = best.latest_chapter_title
                    c_num = best.latest_chapter_num
                    c_url = best.latest_chapter_url
                    c_src = best.source_name

            # Wait for official probe
            off_info = await off_task
            self.tracker.add_book(
                book_name=name,
                author=author,
                latest_chapter=c_chap,
                latest_chapter_num=c_num,
                latest_chapter_url=c_url,
                source_name=c_src,
                official_chapter=off_info.get("official_chapter", ""),
                official_chapter_num=off_info.get("official_num", 0.0),
                official_source=off_info.get("official_source", ""),
                official_url=off_info.get("official_url", ""),
                official_time=off_info.get("official_time", ""),
                crawlable_chapter=c_chap,
                crawlable_chapter_num=c_num,
                crawlable_source=c_src,
                catalog_url=cat_url
            )
        return web.json_response({"status": "success"})

    async def handle_remove_bookshelf(self, request: web.Request) -> web.Response:
        data = await request.json()
        name = data.get("name", "").strip()
        if name:
            self.tracker.remove_book(name)
        return web.json_response({"status": "success"})

    async def handle_check_bookshelf(self, request: web.Request) -> web.Response:
        books = self.tracker.get_all()
        for b in books:
            name = b.get("book_name", "")
            if not name:
                continue

            off_task = asyncio.create_task(self.official_prober.probe(name))

            c_chap = ""
            c_num = 0.0
            c_url = ""
            c_src = "全网聚合"
            cat_url = ""

            # 1. Check SourceCache first
            cached = self.source_cache.get(name)
            if cached and cached.get("catalog_url"):
                try:
                    meta, chaps = await self.catalog_extractor.discover_catalog(cached["catalog_url"])
                    if chaps:
                        last_chap = chaps[-1]
                        c_chap = last_chap[1]
                        c_num = last_chap[3]
                        c_url = last_chap[2]
                        c_src = cached.get("source_name", "全网聚合")
                        cat_url = cached["catalog_url"]
                except Exception:
                    pass

            # 2. Fallback to SourceManager
            if not c_chap:
                best, _ = await self.sources_manager.search_novel(name)
                if best:
                    c_chap = best.latest_chapter_title
                    c_num = best.latest_chapter_num
                    c_url = best.latest_chapter_url
                    c_src = best.source_name

            off_info = await off_task
            is_new, old_title = self.tracker.check_and_update(
                book_name=name,
                new_chapter_title=c_chap,
                new_chapter_num=c_num,
                new_chapter_url=c_url,
                source_name=c_src,
                official_chapter=off_info.get("official_chapter", ""),
                official_chapter_num=off_info.get("official_num", 0.0),
                official_source=off_info.get("official_source", ""),
                official_url=off_info.get("official_url", ""),
                official_time=off_info.get("official_time", ""),
                crawlable_chapter=c_chap,
                crawlable_chapter_num=c_num,
                crawlable_source=c_src,
                catalog_url=cat_url
            )
            if is_new:
                self.notifier.notify_update(
                    book_name=name,
                    new_chapter=c_chap,
                    old_chapter=old_title,
                    source_url=c_url
                )
        return web.json_response({"status": "success"})

    async def handle_list_files(self, request: web.Request) -> web.Response:
        file_list = []
        if os.path.exists(self.output_dir):
            for fname in os.listdir(self.output_dir):
                fpath = os.path.join(self.output_dir, fname)
                if os.path.isfile(fpath):
                    size_bytes = os.path.getsize(fpath)
                    if size_bytes >= 1024 * 1024:
                        size_str = f"{size_bytes / (1024 * 1024):.2f} MB"
                    else:
                        size_str = f"{size_bytes / 1024:.1f} KB"
                    mtime = datetime.fromtimestamp(os.path.getmtime(fpath)).strftime("%Y-%m-%d %H:%M")
                    ext = fname.split(".")[-1].lower() if "." in fname else ""
                    file_list.append({
                        "name": fname,
                        "ext": ext,
                        "size_bytes": size_bytes,
                        "size_formatted": size_str,
                        "modified": mtime
                    })
        file_list.sort(key=lambda x: x["modified"], reverse=True)
        return web.json_response({"files": file_list})

    async def handle_download_file(self, request: web.Request) -> web.Response:
        filename = urllib.parse.unquote(request.match_info["filename"])
        filepath = os.path.join(self.output_dir, filename)
        if not os.path.exists(filepath):
            return web.Response(status=404, text="File Not Found")
        return web.FileResponse(filepath, chunk_size=512 * 1024)

    async def handle_extract_stream(self, request: web.Request) -> web.StreamResponse:
        data = await request.json()
        target = data.get("target", "").strip()
        formats = data.get("formats", ["epub", "txt"])
        start = data.get("start", 1)
        limit = data.get("limit")

        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no"
            }
        )
        await resp.prepare(request)

        async def stream_print(msg: str):
            await resp.write(f"{msg}\n".encode("utf-8"))

        await stream_print(f"=================================================================")
        await stream_print(f"🌐 【UniversalNovelExtractor 通用小说提取器】启动")
        await stream_print(f"🎯 目标输入: {target}")
        await stream_print(f"📦 导出格式: {','.join(formats)}")
        await stream_print(f"=================================================================")

        try:
            extractor = UniversalNovelExtractor(output_dir=self.output_dir, concurrency=12)
            results = await extractor.extract(
                input_target=target,
                formats=formats,
                start_chapter=start,
                limit_chapters=limit,
                custom_output_dir=self.output_dir,
                log_callback=stream_print
            )
            await stream_print("\n🎉 全流程提取完成！")
            for fmt, path in results.items():
                await stream_print(f"  ✓ [{fmt.upper()} 导出路径] -> {path}")
        except Exception as e:
            await stream_print(f"\n❌ 提取失败: {e}")

        await resp.write_eof()
        return resp

    async def handle_opds(self, request: web.Request) -> web.Response:
        from core.legado_bridge import LegadoBridge
        bridge = LegadoBridge(downloads_dir=self.output_dir)
        host_url = f"{request.scheme}://{request.host}"
        feed_xml = bridge.generate_opds_feed(host_url)
        return web.Response(text=feed_xml, content_type="application/atom+xml", charset="utf-8")

    async def handle_legado_sources(self, request: web.Request) -> web.Response:
        from core.legado_bridge import LegadoBridge
        bridge = LegadoBridge()
        sources = bridge.generate_legado_book_sources()
        return web.json_response(sources)

    async def handle_legado_apk(self, request: web.Request) -> web.Response:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        apk_path = os.path.join(base_dir, "client", "legado-3.26-arm64.apk")
        if os.path.exists(apk_path):
            return web.FileResponse(apk_path, chunk_size=512 * 1024)
        upstream_url = "https://github.com/huajideshutiao/legado/releases/download/3.26.100113/legado-3.26.100113-huaji-arm64-v8a-release.apk"
        raise web.HTTPFound(upstream_url)

    async def handle_legado_info(self, request: web.Request) -> web.Response:
        from core.legado_bridge import get_local_ip
        lan_ip = get_local_ip()
        base_dir = os.path.dirname(os.path.dirname(__file__))
        apk_path = os.path.join(base_dir, "client", "legado-3.26-arm64.apk")
        return web.json_response({
            "lan_ip": lan_ip,
            "port": self.port,
            "opds_url": f"http://{lan_ip}:{self.port}/opds",
            "sources_url": f"http://{lan_ip}:{self.port}/api/legado/sources.json",
            "apk_url": f"http://{lan_ip}:{self.port}/legado.apk",
            "apk_exists": os.path.exists(apk_path)
        })

    async def handle_webdav(self, request: web.Request) -> web.Response:
        """Handle WebDAV protocol (PROPFIND, OPTIONS) for Legado 远程书籍."""
        from xml.sax.saxutils import escape
        from datetime import timezone
        method = request.method.upper()
        if method == "OPTIONS":
            return web.Response(
                status=200,
                headers={
                    "DAV": "1, 2",
                    "Allow": "OPTIONS, GET, HEAD, PROPFIND",
                    "MS-Author-Via": "DAV"
                }
            )

        if method == "PROPFIND":
            req_path = request.path
            responses = []

            # Collection root
            responses.append(f"""  <D:response>
    <D:href>{req_path}</D:href>
    <D:propstat>
      <D:prop>
        <D:resourcetype><D:collection/></D:resourcetype>
        <D:displayname>NovelTracker</D:displayname>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>""")

            if os.path.exists(self.output_dir):
                for fname in sorted(os.listdir(self.output_dir)):
                    if fname.lower().endswith((".epub", ".txt")):
                        fpath = os.path.join(self.output_dir, fname)
                        size = os.path.getsize(fpath)
                        mtime = datetime.fromtimestamp(os.path.getmtime(fpath), timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
                        is_epub = fname.lower().endswith(".epub")
                        ctype = "application/epub+zip" if is_epub else "text/plain"
                        quoted_name = urllib.parse.quote(fname)

                        responses.append(f"""  <D:response>
    <D:href>/api/download/{quoted_name}</D:href>
    <D:propstat>
      <D:prop>
        <D:displayname>{escape(fname)}</D:displayname>
        <D:getcontentlength>{size}</D:getcontentlength>
        <D:getlastmodified>{mtime}</D:getlastmodified>
        <D:resourcetype/>
        <D:getcontenttype>{ctype}</D:getcontenttype>
      </D:prop>
      <D:status>HTTP/1.1 200 OK</D:status>
    </D:propstat>
  </D:response>""")

            xml_content = f"""<?xml version="1.0" encoding="utf-8"?>
<D:multistatus xmlns:D="DAV:">
{chr(10).join(responses)}
</D:multistatus>"""
            return web.Response(
                status=207,
                text=xml_content,
                content_type="application/xml",
                charset="utf-8",
                headers={"DAV": "1, 2"}
            )

        return web.Response(status=405, text="Method Not Allowed")

    def start(self, auto_open: bool = True):
        app = web.Application()
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/api/bookshelf", self.handle_get_bookshelf)
        app.router.add_post("/api/bookshelf/add", self.handle_add_bookshelf)
        app.router.add_post("/api/bookshelf/remove", self.handle_remove_bookshelf)
        app.router.add_post("/api/bookshelf/check", self.handle_check_bookshelf)
        app.router.add_get("/api/files", self.handle_list_files)
        app.router.add_get("/api/download/{filename}", self.handle_download_file)
        app.router.add_post("/api/extract", self.handle_extract_stream)

        # Legado (阅读 3.0) Integration Endpoints (OPDS + WebDAV)
        app.router.add_get("/opds", self.handle_opds)
        app.router.add_get("/api/legado/sources.json", self.handle_legado_sources)
        app.router.add_get("/api/legado/info", self.handle_legado_info)
        app.router.add_get("/legado.apk", self.handle_legado_apk)

        # WebDAV Support for Legado 3.0 "远程书籍"
        for p in ["/", "/opds", "/webdav", "/downloads", "/downloads/"]:
            app.router.add_route("PROPFIND", p, self.handle_webdav)
            app.router.add_route("OPTIONS", p, self.handle_webdav)
        app.router.add_get("/webdav", self.handle_webdav)
        app.router.add_get("/downloads/{filename}", self.handle_download_file)

        local_url = f"http://127.0.0.1:{self.port}"
        from core.legado_bridge import get_local_ip
        lan_ip = get_local_ip()

        print("=" * 65)
        print("[+] NovelTracker 2.0 Web Dashboard started")
        print(f"[*] Local access: {local_url}")
        print(f"[*] Storage path: {os.path.abspath(self.output_dir)}")
        print("-" * 65)
        print("[+] Legado (阅读 3.0) Mobile Integration:")
        print(f"  [-] OPDS Catalog Feed : http://{lan_ip}:{self.port}/opds")
        print(f"  [-] BookSource Sync   : http://{lan_ip}:{self.port}/api/legado/sources.json")
        print(f"  [-] Legado arm64 APK  : http://{lan_ip}:{self.port}/legado.apk")
        print("Press Ctrl+C to stop.")
        print("=" * 65 + "\n")

        if auto_open:
            import webbrowser
            try:
                webbrowser.open(local_url)
            except Exception:
                pass

        web.run_app(app, host=self.host, port=self.port)


if __name__ == "__main__":
    app = WebApp()
    app.start()
