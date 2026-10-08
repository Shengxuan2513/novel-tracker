# EPUB 更新缓存修复

源码基于社区 Fork `huajideshutiao/legado` 标签 `3.26.100113`，提交 `c290beb185172801040ac3d4c519ec07db867ae7`。
修改后的完整源码在 `legado-source/`，原社区 APK 保留在 `legado-3.26-arm64.apk`。

修复 APK 已成功构建：`legado-epubfix-arm64.apk`，33,997,847 字节；APK v2 签名验证通过。
SHA-256：`003234cb80d1e0895b5e35146ef4159b39d30de7b5d3d97e928b5e77cdf260f6`。
完整 Android 编译已通过，尚未在手机上实测。
首次本地验证中，服务器完整下载的 SHA-256 与本地 APK 一致，HTTP Range 已验证。

## 行为

- 同名 EPUB 重新导入时释放旧 ZIP 文件句柄，不再复用旧的章节偏移。
- 打开 EPUB 时先检查文件版本，再决定是否使用数据库里的旧目录。相邻检查间隔 15 秒。
- 远程 EPUB 从当前文件重新定位 ZIP 中央目录，忽略没有版本标识的历史偏移缓存。
- 每次远程分段读取都核对 ETag、修改时间、文件长度和 Content-Range。文件在读取期间更新时显示更新提示，避免拼接两个版本的内容。
- 服务器支持返回 HTTP 410 和 `X-NovelTracker-Latest-URL` 时，修复版可读取同源最新地址。此能力需要额外的服务端版本下载适配；本客户端 PR 不包含该适配。
- 目录重建时优先按原章节标题恢复位置；标题缺失时保留最接近的有效序号。章节内位置保留，正文有增删时页码可能改变。
- 重新导入沿用原书籍记录，不删除书签、书架分组等数据。书签未做跨版本章节重排迁移；正常追加章节不改变已有章节序号。

## 手机使用

修复 APK 使用 `shutiao.reader.debug` 包名，显示为“阅读（EPUB修复版）”，与原发行应用并存。
采用本地 Gradle debug 签名，不能覆盖安装不同签名的原发行包。后续覆盖安装须保持包名、签名密钥一致，并递增 versionCode。当前为测试版；正式发布应使用固定发布密钥，切勿提交私钥。

1. 在原阅读应用中执行备份，保留备份文件。
2. 安装修复版，在修复版中恢复备份，并重新选择原书籍文件夹授予修复版读取权限。
3. 使用原 OPDS 地址 `http://192.168.137.1:5000/opds`。
4. 远程按需读取的书籍：电脑更新后重新打开书籍，或执行“更新目录”。
5. 已经完整下载到手机的书籍：仍需下载新版文件并覆盖/重新导入同名书籍，随后更新目录；不必先删除书架中的书籍。手机上的独立副本不会随电脑文件自动改变。

## 验证与构建

客户端核心回归测试 23 项通过，包含真实 ZIP 经 HTTP Range 读取、替换前后第 233 章偏移变化、读取中更新拒绝旧版本、旧地址恢复、章节位置匹配。
核心测试直接编译修改的 Kotlin 源文件；它们不等同于完整 Android 构建或手机实测。

构建工具位于被 Git 忽略的 `storage/reader-toolchain/`。脚本创建按项目区分的 ASCII 目录联接，避免 Windows 中文路径导致的 Java 参数文件问题；可通过 `-BuildRoot` 指定位置。

从 novel-tracker 项目根目录运行：

```powershell
python scripts/prepare_reader_source.py
python scripts/prepare_reader_toolchain.py
powershell -File scripts/build_reader.ps1 -Mode test
powershell -File scripts/build_reader.ps1 -Mode apk
```

首次构建还需要 Android SDK 的 `platforms;android-37.0`、`build-tools;37.0.0`、`platform-tools`，运行解压后的 `cmdline-tools/bin/sdkmanager.bat --sdk_root=<SDK目录> --licenses` 阅读并接受 SDK 许可后，再安装这些组件；其余 SDK/NDK 依赖由 Gradle 安装。SDK 目录为 `storage/reader-toolchain/android-sdk`。
如需保存构建日志，可使用 PowerShell `Tee-Object`。运行 `python scripts/package_reader_source.py` 生成对应的完整源码压缩包（包含未修改的基础源码、修复代码、测试和构建说明）。
构建成功后安装包保存为 `client/legado-epubfix-arm64.apk`，手机通过热点下载：[下载 EPUB 修复版](http://192.168.137.1:5000/legado-fixed.apk)。
