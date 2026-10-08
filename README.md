# NovelTracker

小说检索、下载、追更与本地文件维护工具。提供浏览器界面和命令行，支持 TXT、EPUB、JSON 导出，以及「阅读 3.0（Legado）」局域网书库接入。

[快速开始](#快速开始) · [日常使用](#日常使用) · [手机阅读](#手机阅读legado) · [常见问题](#常见问题) · [开发与测试](#开发与测试)

## 能做什么

| 操作 | 用途 |
| --- | --- |
| 搜索与提取 | 输入书名或小说页面网址，寻找目录并提取章节 |
| 文件导出 | 导出 TXT、EPUB、JSON，可指定章节范围 |
| 本地续更 | 读取已有 TXT/EPUB，补抓缺失或残缺章节，并获取新章节 |
| 文件体检 | 检查断号、短章及疑似异常正文，可尝试联网修复 |
| 追更书架 | 收藏书籍，定期检查更新并提醒 |
| 手机接入 | 通过 OPDS 或 WebDAV 获取电脑书库中的文件，导入配套书源 |
| 浏览器接力 | 配合油猴脚本，将浏览器中已打开页面的正文发送到本地 |

提取结合站点规则和通用正文分析。网站访问限制、目录结构和正文质量会影响结果；任务会区分完成、部分完成与失败。

## 快速开始

需要安装 Python 和 Git。安装配置声明 Python 3.8 及以上；本次修复在 Windows / Python 3.14 上验证，其他版本尚未逐一复测。

### Windows（PowerShell）

在准备存放项目的目录打开 PowerShell，依次执行：

```powershell
git clone https://github.com/Shengxuan2513/novel-tracker.git
cd novel-tracker
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe cli.py web --port 5000
```

以上命令直接使用虚拟环境中的 Python，无需激活环境。后续命令示例中的 `python`，在 Windows 下可替换为 `.\.venv\Scripts\python.exe`。

### macOS / Linux

```bash
git clone https://github.com/Shengxuan2513/novel-tracker.git
cd novel-tracker
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
python cli.py web --port 5000
```

### 第一次使用

1. 启动后打开浏览器中的 `http://127.0.0.1:5000`。
2. 输入书名或目录页网址，选择导出格式，开始提取。
3. 查看任务结果；如果有未完成章节，根据提示重试。
4. 在「下载文件」中获取 TXT 或 EPUB。

运行期间保持终端窗口打开，按 `Ctrl+C` 停止服务。下次使用时进入项目目录，重新执行启动命令即可。

## 日常使用

优先使用浏览器界面。需要批量操作或维护已有文件时，可在项目目录运行以下命令。

### 搜索、下载与范围提取

```bash
python cli.py search "宿命之环"
python cli.py extract "宿命之环" -f txt,epub
python cli.py extract "宿命之环" --start 1 --limit 50 -f all
```

`extract` 也接受小说详情页、目录页或章节页的网址。`-f all` 导出 TXT、EPUB 和 JSON；`--start` 是起始章节号，`--limit` 是最多提取的章节数。默认保存到数据目录下的 `downloads`，可用 `-o` 指定其他目录。

### 已有文件续更与修复

```bash
python cli.py update-file "downloads/《书名》.txt"
python cli.py audit "downloads/《书名》.epub"
python cli.py audit "downloads/《书名》.epub" --fix
```

将示例路径换成实际文件路径。`audit` 只做检查，添加 `--fix` 后尝试修复；续更与修复可用 `-s "目录页网址"` 指定来源，自动搜索无法找到正确书籍时可以使用此选项。

- 续更会重试本地已有范围内的缺章、残章，再获取新章节；部分完成会保留未修复内容并提示剩余问题。
- TXT 和 EPUB 先生成并校验，再替换目标文件，旧版本保留为同路径的 `.bak`。正常写入异常会回退旧文件。
- 范围提取使用含章节范围的独立文件名；含暂缺章节的提取结果带「未完整」，避免覆盖已有完整版本。
- 无法确认身份或完整性的旧缓存会重新抓取。旧缓存目录不会被清空。

不要在文件发布期间手工编辑同一文件。突然断电发生在 TXT 与 EPUB 的替换之间时，可能留下不同版本，可使用对应的 `.bak` 恢复。

### 追更书架

```bash
python cli.py follow "宿命之环"
python cli.py list
python cli.py check
python cli.py monitor -i 15
python cli.py unfollow "宿命之环"
```

`monitor -i 15` 每 15 分钟检查一次，需保持进程运行。`check` / `monitor` 负责检查更新并提醒；更新本地 TXT/EPUB 请运行 `update-file`。

## 手机阅读（Legado）

电脑和手机连接同一局域网，在电脑启动：

```bash
python cli.py legado --port 5000
```

终端会显示实际局域网地址。在阅读 App 中使用相应入口填写链接：

| 入口 | 链接示例 |
| --- | --- |
| OPDS 外部书库 | `http://电脑局域网IP:5000/opds` |
| WebDAV 远程书籍 | `http://电脑局域网IP:5000/webdav` |
| 书源管理 → 网络导入 | `http://电脑局域网IP:5000/api/legado/sources.json` |

将「电脑局域网IP」换成终端显示的地址，不要在手机上填写 `127.0.0.1`。使用其他端口时，同时修改链接中的端口。手机访问期间保持电脑服务运行。

服务器文件续更后，手机上已经下载的副本需重新获取。OPDS 下载使用版本地址和不可变文件快照，避免旧章节偏移读取新版 EPUB；旧地址返回更新提示，普通客户端需刷新书库后重新获取。

[配套修复客户端](client/EPUB修复说明.md) 支持按服务器返回的最新地址恢复读取，安装与源码构建步骤见该文档。电脑放置配套 APK 后可通过 `/legado-fixed.apk` 下载；未放置时返回明确的缺失提示。OPDS/WebDAV 及客户端下载接口已做自动化验证，本次未进行手机实机测试或重新构建 Android APK。

下载快照保存在 `downloads/.download-snapshots/`，会占用磁盘；需要清理时先停止服务，再删除该目录。版本协议与限制见 [版本下载说明](docs/versioned-downloads.md)。

仅查看链接可用 `python cli.py legado --info`；停止或重启本项目的服务可用 `--stop` / `--restart`，并指定与运行时相同的 `--port`。

## 文件保存在哪里

| 运行方式 | 默认数据根目录 |
| --- | --- |
| 从源码运行（包括 `pip install -e .`） | 项目目录 |
| 普通安装包，Windows | `%LOCALAPPDATA%\NovelTracker` |
| 普通安装包，macOS / Linux | `$XDG_DATA_HOME/novel-tracker`，未设置时为 `~/.local/share/novel-tracker` |

下载文件位于数据根目录的 `downloads` 中，书架和缓存也使用同一数据根目录；切换启动位置不会改变默认书库。可设置环境变量 `NOVEL_TRACKER_DATA_DIR` 指定数据根目录。

普通安装包可从任意目录使用 `novel-tracker web` 等命令，将示例中的 `python cli.py` 替换为 `novel-tracker`。

## 常见问题

**启动提示端口被占用**：换一个端口，例如 `python cli.py web --port 5001`，浏览器访问 `http://127.0.0.1:5001`。停止服务只会处理能确认属于本项目的进程。

**书名搜索没有结果或选错书**：尝试输入明确的目录页网址；维护已有文件时用 `-s` 指定来源，并核对书名与作者。

**任务部分完成**：先查看失败章节，确认来源可访问后重试。文件体检中的短章提示需要结合正文判断，篇幅短不一定代表损坏。

**手机无法连接**：核对电脑局域网 IP、服务端口、双方网络及防火墙是否允许连接。WebDAV 地址应填入 App 的 WebDAV 入口，不能用普通网页访问来判断是否可用。

**需要浏览器接力**：运行 `python cli.py relay --port 8765`，配合 [油猴脚本](scripts/novel_relay.user.js) 使用。接力发送的是浏览器中已经打开的正文页面。

更多参数可运行 `python cli.py --help`，或 `python cli.py extract --help` 等子命令帮助。

## 开发与测试

```bash
python -m pip install -e ".[test]"
python -m pytest tests -q
```

整合客户端接口、版本下载和六项稳定性修复后的回归测试共 **105 项**，覆盖章节完整性、缺章修复、多页拼接、文件发布回退、缓存身份、请求校验、版本下载、配套 APK 接口及阅读接口。测试使用受控数据，不能代表所有在线书源始终可用；测试结果与范围见 PR #7。

代码入口为 [cli.py](cli.py)，主要实现位于 [core](core)，回归用例位于 [tests](tests)。

## 许可证

本项目使用 [MIT 许可证](LICENSE)。请遵守内容授权与来源站点的使用规则。
