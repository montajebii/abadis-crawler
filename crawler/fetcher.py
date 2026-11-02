"""Playwright-based fetcher with resource blocking + AIMD + UA rotation.

Works on both desktop (standard playwright) and Termux (amv-playwright).
"""
from __future__ import annotations

import asyncio
import os
import platform
from dataclasses import dataclass
from typing import Optional

from crawler.logger import setup_logger
from crawler.throttle import AIMDController, BackoffExhausted
from crawler.useragent import UserAgentRotator


def is_termux() -> bool:
    return "com.termux" in os.environ.get("PREFIX", "") or (
        platform.system() == "Linux"
        and os.path.isdir("/data/data/com.termux")
    )


@dataclass
class FetchResult:
    url: str
    status: int
    html: Optional[str]
    error: Optional[str] = None


class Fetcher:
    def __init__(
        self,
        throttle: AIMDController,
        ua_rotator: UserAgentRotator,
        blocked_domains: Optional[list[str]] = None,
        block_resources: Optional[list[str]] = None,
        headless: bool = True,
        timeout_ms: int = 30000,
    ):
        self.throttle = throttle
        self.ua_rotator = ua_rotator
        self.blocked_domains = set(blocked_domains or [])
        self.block_resources = set(block_resources or [])
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.log = setup_logger("fetcher")
        self._browser = None
        self._context = None
        self._playwright = None

    async def __aenter__(self) -> "Fetcher":
        await self._start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._stop()

    async def _start(self) -> None:
        if is_termux():
            from amv_playwright.async_api_termux import async_playwright  # type: ignore
            self.log.info("Launching Playwright in Termux mode (amv-playwright)")
        else:
            from playwright.async_api import async_playwright  # type: ignore
            self.log.info("Launching Playwright in desktop mode")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        self._context = await self._browser.new_context(
            user_agent=self.ua_rotator.current,
            viewport={"width": 1366, "height": 900},
            locale="fa-IR",
            timezone_id="Asia/Tehran",
        )
        await self._context.route("**/*", self._route_handler)

    async def _route_handler(self, route) -> None:
        req = route.request
        url = req.url
        if any(domain in url for domain in self.blocked_domains):
            await route.abort()
            return
        if req.resource_type in self.block_resources:
            await route.abort()
            return
        await route.continue_()

    async def _rotate_ua_if_needed(self) -> None:
        new_ua = self.ua_rotator.get()
        if self._context is not None and new_ua != self.ua_rotator.current:
            try:
                await self._context.set_extra_http_headers({"User-Agent": new_ua})
            except Exception as e:
                self.log.debug(f"UA header update failed: {e}")

    async def _stop(self) -> None:
        for closer in (self._context, self._browser):
            if closer is not None:
                try:
                    await closer.close()
                except Exception:
                    pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass

    async def fetch(self, url: str, wait_selector: Optional[str] = None) -> FetchResult:
        """Fetch a URL with AIMD throttling, backoff on 429/503, and UA rotation."""
        await self.throttle.wait()
        await self._rotate_ua_if_needed()

        page = await self._context.new_page()
        try:
            # Two quick retries on transient network errors
            # (ERR_NETWORK_CHANGED is common when Wi-Fi <-> mobile data
            #  switches on Termux; the OS-level session survives).
            response = None
            last_exc = None
            for attempt in range(3):
                try:
                    response = await page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=self.timeout_ms,
                    )
                    last_exc = None
                    break
                except Exception as exc:
                    last_exc = exc
                    msg = str(exc)
                    if (
                        "ERR_NETWORK_CHANGED" in msg
                        or "ERR_INTERNET_DISCONNECTED" in msg
                        or "ERR_NETWORK_IO_SUSPENDED" in msg
                    ):
                        self.log.info(
                            f"transient network error on {url} "
                            f"(attempt {attempt+1}/3); retrying in 3s"
                        )
                        await asyncio.sleep(3)
                        continue
                    raise
            if last_exc is not None:
                raise last_exc
            status = response.status if response else 0

            if status in (429, 503):
                sleep_for = self.throttle.on_rate_limited()
                self.log.warning(
                    f"Rate limited ({status}) on {url}; sleeping {sleep_for}s"
                )
                await asyncio.sleep(sleep_for)
                return FetchResult(url=url, status=status, html=None,
                                   error=f"HTTP {status}")

            if status == 200 and wait_selector:
                try:
                    await page.wait_for_selector(wait_selector, timeout=10000)
                except Exception:
                    self.log.debug(f"wait_for_selector timeout on {url}")

            html = await page.content()
            self.throttle.on_success()
            return FetchResult(url=url, status=status, html=html)
        except BackoffExhausted:
            raise
        except Exception as e:
            self.log.error(f"Fetch error on {url}: {e}")
            return FetchResult(url=url, status=0, html=None, error=str(e))
        finally:
            await page.close()

    @property
    def stats(self) -> dict:
        return {
            **self.throttle.snapshot(),
            "current_ua": self.ua_rotator.current[:50] + "...",
        }
