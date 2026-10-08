"""
Notification module for novel updates.
Supports Terminal Highlights, Windows Toast / System notifications, and Webhooks.
"""

import json
import os
import sys
from typing import Optional
from core.paths import data_dir
import httpx


class Notifier:
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            base_dir = data_dir()
            self.config_path = os.path.join(base_dir, "config.json")
        else:
            self.config_path = config_path
            
        self.config = self.load_config()

    def load_config(self) -> dict:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "pushplus_token": "",
            "serverchan_sendkey": "",
            "custom_webhook_url": "",
            "enable_desktop_notification": True
        }

    def notify_update(
        self,
        book_name: str,
        new_chapter: str,
        old_chapter: Optional[str] = None,
        chapter_url: str = "",
        source_name: str = ""
    ) -> None:
        """
        Send notification through enabled channels.
        """
        title = f"📖 《{book_name}》更新啦！"
        message = f"最新章节：{new_chapter}"
        if old_chapter:
            message += f"\n上一章节：{old_chapter}"
        if source_name:
            message += f"\n更新来源：{source_name}"
        if chapter_url:
            message += f"\n阅读链接：{chapter_url}"

        # 1. Console display
        print("\n" + "=" * 55)
        print(f" 🔥 【小说更新通知】 {title}")
        print("-" * 55)
        print(f" 📚 书名: 《{book_name}》")
        print(f" 🆕 最新: {new_chapter}")
        if old_chapter:
            print(f" 📜 原先: {old_chapter}")
        if source_name:
            print(f" 🌐 来源: {source_name}")
        if chapter_url:
            print(f" 🔗 链接: {chapter_url}")
        print("=" * 55 + "\n")

        # 2. Desktop Notification
        if self.config.get("enable_desktop_notification", True):
            self._send_desktop_notification(title, f"{new_chapter}\n来源: {source_name}")

        # 3. Webhook / Push services (Async trigger or fast sync)
        self._send_pushplus(title, message)
        self._send_serverchan(title, message)
        self._send_custom_webhook(title, message)

    def _send_desktop_notification(self, title: str, message: str) -> None:
        """Send Windows notification via PowerShell if on Windows."""
        if sys.platform == "win32":
            try:
                import subprocess
                title_literal = "'" + title.replace("'", "''") + "'"
                message_literal = "'" + message.replace("'", "''") + "'"
                ps_script = f"""
                [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
                $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
                $textNodes = $template.GetElementsByTagName("text")
                $textNodes.Item(0).AppendChild($template.CreateTextNode({title_literal})) > $null
                $textNodes.Item(1).AppendChild($template.CreateTextNode({message_literal})) > $null
                $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("NovelTracker")
                $notification = [Windows.UI.Notifications.ToastNotification]::new($template)
                $notifier.Show($notification)
                """
                subprocess.Popen(
                    ["powershell", "-NoProfile", "-Command", ps_script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
            except Exception:
                pass

    def _send_pushplus(self, title: str, content: str) -> None:
        token = self.config.get("pushplus_token", "").strip()
        if not token:
            return
        try:
            url = "http://www.pushplus.plus/send"
            data = {
                "token": token,
                "title": title,
                "content": content.replace("\n", "<br/>"),
                "template": "html"
            }
            httpx.post(url, json=data, timeout=5.0)
        except Exception as e:
            print(f"[PushPlus] 推送失败: {e}")

    def _send_serverchan(self, title: str, desp: str) -> None:
        sendkey = self.config.get("serverchan_sendkey", "").strip()
        if not sendkey:
            return
        try:
            url = f"https://sctapi.ftqq.com/{sendkey}.send"
            data = {"title": title, "desp": desp}
            httpx.post(url, data=data, timeout=5.0)
        except Exception as e:
            print(f"[Server酱] 推送失败: {e}")

    def _send_custom_webhook(self, title: str, content: str) -> None:
        url = self.config.get("custom_webhook_url", "").strip()
        if not url:
            return
        try:
            data = {"title": title, "text": content}
            httpx.post(url, json=data, timeout=5.0)
        except Exception as e:
            print(f"[Webhook] 推送失败: {e}")
