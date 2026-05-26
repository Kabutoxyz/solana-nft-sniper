"""Notification system: Telegram and desktop notifications."""

import asyncio
import logging
import subprocess
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


class Notifier:
    def __init__(self, telegram_token: str = "", telegram_chat_id: str = "",
                 desktop: bool = True):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.desktop_enabled = desktop and self._has_desktop()

    @staticmethod
    def _has_desktop() -> bool:
        """Check if a desktop notification tool is available."""
        for cmd in ("notify-send", "osascript"):
            if shutil.which(cmd):
                return True
        return False

    async def send(self, title: str, message: str, urgent: bool = False) -> None:
        """Send notification via all enabled channels."""
        tasks = []
        if self.telegram_token and self.telegram_chat_id and HAS_HTTPX:
            tasks.append(self._send_telegram(message))
        if self.desktop_enabled:
            tasks.append(self._send_desktop(title, message))
        if not tasks:
            logger.info(f"[NOTIFY] {title}: {message}")
            return
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.error(f"Notification error: {r}")

    async def _send_telegram(self, message: str) -> None:
        """Send message via Telegram Bot API."""
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                logger.error(f"Telegram send failed: {resp.status_code} {resp.text}")
            else:
                logger.debug("Telegram notification sent")

    async def _send_desktop(self, title: str, message: str) -> None:
        """Send desktop notification using OS-native tool."""
        try:
            if shutil.which("notify-send"):
                urgency = "critical" if "ALERT" in title.upper() else "normal"
                proc = await asyncio.create_subprocess_exec(
                    "notify-send", f"--urgency={urgency}", title, message,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            elif shutil.which("osascript"):
                script = f'display notification "{message}" with title "{title}"'
                proc = await asyncio.create_subprocess_exec(
                    "osascript", "-e", script,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
        except Exception as e:
            logger.warning(f"Desktop notification failed: {e}")

    async def notify_new_mint(self, name: str, mint_address: str, price: float,
                              supply: int) -> None:
        """Notify about a new NFT mint opportunity."""
        msg = (
            f"🎨 *New NFT Mint Detected*\n"
            f"Name: {name}\n"
            f"Mint: `{mint_address}`\n"
            f"Price: {price} SOL\n"
            f"Supply: {supply}"
        )
        await self.send("NFT ALERT", msg, urgent=True)

    async def notify_mint_success(self, mint_address: str, tx_sig: str) -> None:
        """Notify about a successful mint transaction."""
        msg = (
            f"✅ *Mint Successful!*\n"
            f"Mint: `{mint_address}`\n"
            f"Tx: `{tx_sig}`"
        )
        await self.send("Mint Success", msg)

    async def notify_mint_failure(self, mint_address: str, reason: str) -> None:
        """Notify about a failed mint attempt."""
        msg = (
            f"❌ *Mint Failed*\n"
            f"Mint: `{mint_address}`\n"
            f"Reason: {reason}"
        )
        await self.send("Mint Failed", msg)
