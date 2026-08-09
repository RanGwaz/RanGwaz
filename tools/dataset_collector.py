#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Collect authorized image datasets with a visible browser session.

The tool intentionally does not bypass CAPTCHA, paywalls, or platform limits.
For pages that require a login, it can fill the configured account in the
visible browser; CAPTCHA or second-factor checks still require user action.
The browser profile is kept under tools/.collector_browser.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import html
import io
import json
import mimetypes
import os
import queue
import re
import sys
import threading
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "tools" / "downloaded_dataset"
DEFAULT_BROWSER_PROFILE = ROOT / "tools" / ".collector_browser"
DEFAULT_LOGIN_EMAIL = os.environ.get("RANGWAZ_LOGIN_EMAIL", "")
DEFAULT_LOGIN_PASSWORD = os.environ.get("RANGWAZ_LOGIN_PASSWORD", "")
DEFAULT_TARGET_IMAGES = 80_000
DEFAULT_START_SCROLLS = 12
DEFAULT_DETAIL_PAGES = 320
DEFAULT_DETAIL_SCROLLS = 26
DEFAULT_DETAIL_TARGET_IMAGES = 260
DEFAULT_LOGIN_WAIT_SECONDS = 240
DEFAULT_DOWNLOAD_WORKERS = 10
DEFAULT_SCROLL_PAUSE = 0.9
DEFAULT_REQUEST_DELAY = 0.12
DEFAULT_MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_IMAGE_PIXELS = 40_000_000
DOWNLOAD_CHUNK_BYTES = 64 * 1024

PINIMG_HOST_RE = re.compile(r"(^|\.)pinimg\.com$", re.IGNORECASE)
PIN_DETAIL_RE = re.compile(
    r"(?:https?://(?:www\.)?pinterest\.com)?/pin/([0-9]+)/?",
    re.IGNORECASE,
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
IMAGE_FORMAT_MIME_TYPES = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "GIF": "image/gif",
    "BMP": "image/bmp",
}
PINIMG_SIZE_SEGMENT_RE = re.compile(r"^\d+x$|^x\d+$|^\d+x\d+$", re.IGNORECASE)
PINIMG_SMALL_SEGMENT_RE = re.compile(r"^(\d+)x(\d+)(?:_[A-Z]+)?$", re.IGNORECASE)
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


LogFn = Callable[[str], None]


class LoginGateError(RuntimeError):
    """Collection cannot safely continue because access-gate state is uncertain."""


@dataclass
class ImageCandidate:
    image_url: str
    source_page: str = ""
    detail_url: str = ""
    alt: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    source_kind: str = ""
    fallback_urls: List[str] = field(default_factory=list)


@dataclass
class CollectorConfig:
    output_dir: Path = DEFAULT_OUTPUT_DIR
    dedupe_reference_dirs: List[Path] = field(default_factory=lambda: [DEFAULT_OUTPUT_DIR])
    start_urls: List[str] = field(default_factory=list)
    max_images: int = DEFAULT_TARGET_IMAGES
    max_scrolls: int = DEFAULT_START_SCROLLS
    detail_pages: int = DEFAULT_DETAIL_PAGES
    detail_scrolls: int = DEFAULT_DETAIL_SCROLLS
    detail_target_images: int = DEFAULT_DETAIL_TARGET_IMAGES
    login_wait_seconds: int = DEFAULT_LOGIN_WAIT_SECONDS
    login_email: str = DEFAULT_LOGIN_EMAIL
    login_password: str = DEFAULT_LOGIN_PASSWORD
    scroll_pause: float = DEFAULT_SCROLL_PAUSE
    workers: int = DEFAULT_DOWNLOAD_WORKERS
    request_delay: float = DEFAULT_REQUEST_DELAY
    upgrade_original: bool = True
    pinimg_only: bool = True
    download_images: bool = True
    browser_profile: Path = DEFAULT_BROWSER_PROFILE
    headless: bool = False
    fail_on_login_gate: bool = False
    max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES
    max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS


@dataclass
class DownloadResult:
    ok: bool
    status: str
    image_url: str
    local_path: str = ""
    source_page: str = ""
    detail_url: str = ""
    alt: str = ""
    width: Optional[int] = None
    height: Optional[int] = None
    bytes: int = 0
    sha256: str = ""
    content_type: str = ""
    error: str = ""
    downloaded_at: str = ""


@dataclass
class DownloadIndex:
    seen_candidate_keys: Set[str] = field(default_factory=set)
    candidate_keys: Set[str] = field(default_factory=set)
    sha256_paths: Dict[str, str] = field(default_factory=dict)


def parse_int(value: object) -> Optional[int]:
    try:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return int(float(text))
    except (TypeError, ValueError):
        return None


def clean_text(value: str, limit: int = 500) -> str:
    text = html.unescape(value or "").replace("\x00", "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def normalize_url(value: str, base_url: str = "") -> str:
    if not value:
        return ""
    text = html.unescape(value).strip().strip("\"'")
    text = text.replace("\\/", "/")
    text = text.replace("\\u002F", "/").replace("\\u002f", "/")
    text = unquote(text)
    text = text.rstrip(".,;]")
    if not text:
        return ""
    if text.startswith("//"):
        text = "https:" + text
    elif base_url and text.startswith("/"):
        text = urljoin(base_url, text)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", parsed.query, ""))


def normalize_detail_url(value: str, base_url: str = "") -> str:
    url = normalize_url(value, base_url)
    if not url and value and value.startswith("/"):
        url = urljoin(base_url or "https://www.pinterest.com", value)
    if not url:
        return ""
    parsed = urlparse(url)
    if "pinterest." not in parsed.netloc.lower():
        return ""
    match = PIN_DETAIL_RE.search(parsed.path)
    if not match:
        return ""
    return "https://www.pinterest.com/pin/{}/".format(match.group(1))


def parse_srcset(srcset: str, base_url: str = "") -> List[str]:
    if not srcset:
        return []
    urls: List[str] = []
    for item in html.unescape(srcset).split(","):
        part = item.strip()
        if not part:
            continue
        url = part.split()[0]
        normalized = normalize_url(url, base_url)
        if normalized:
            urls.append(normalized)
    return urls


def choose_primary_image_url(urls: Sequence[str], upgrade_original: bool) -> Tuple[str, List[str]]:
    cleaned: List[str] = []
    seen: Set[str] = set()
    for url in urls:
        normalized = normalize_url(url)
        if not normalized or normalized in seen:
            continue
        cleaned.append(normalized)
        seen.add(normalized)
        if upgrade_original:
            upgraded = upgrade_pinimg_original(normalized)
            if upgraded and upgraded not in seen:
                cleaned.append(upgraded)
                seen.add(upgraded)
    if not cleaned:
        return "", []
    ranked = sorted(cleaned, key=image_quality_score, reverse=True)
    return ranked[0], ranked[1:]


def image_quality_score(url: str) -> int:
    parsed = urlparse(url)
    path = parsed.path.lower()
    score = 0
    if "/originals/" in path:
        score += 1_000_000
    for segment in path.strip("/").split("/"):
        if PINIMG_SIZE_SEGMENT_RE.match(segment):
            nums = [int(num) for num in re.findall(r"\d+", segment)]
            score += max(nums or [0])
    ext = Path(path).suffix
    if ext in {".png", ".webp", ".jpg", ".jpeg"}:
        score += 10
    return score


def upgrade_pinimg_original(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc.lower().endswith("pinimg.com"):
        return ""
    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) < 4:
        return ""
    if parts[0].lower() == "originals":
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    start = 0
    if parts[0].lower().startswith("control") and len(parts) > 4:
        start = 1
    if start < len(parts) and PINIMG_SIZE_SEGMENT_RE.match(parts[start]):
        original_path = "/originals/" + "/".join(parts[start + 1 :])
        return urlunparse((parsed.scheme, parsed.netloc, original_path, "", "", ""))
    return ""


def allowed_image_url(url: str, pinimg_only: bool) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    host = parsed.netloc.lower().split(":")[0]
    suffix = Path(parsed.path.lower()).suffix
    if pinimg_only:
        return host == "i.pinimg.com" and suffix in IMAGE_EXTENSIONS and not is_small_pinimg_asset(parsed.path)
    if suffix in IMAGE_EXTENSIONS:
        return True
    return bool(PINIMG_HOST_RE.search(host))


def is_small_pinimg_asset(path: str) -> bool:
    parts = [part for part in path.strip("/").split("/") if part]
    if not parts:
        return True
    if parts[0].lower() in {"avatars", "videos"}:
        return True
    for part in parts[:2]:
        match = PINIMG_SMALL_SEGMENT_RE.match(part)
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
            return max(width, height) < 200
    return False


def canonical_image_key(candidate: ImageCandidate) -> str:
    primary = upgrade_pinimg_original(candidate.image_url) or candidate.image_url
    parsed = urlparse(primary)
    key = (parsed.netloc.lower() + parsed.path.lower()).strip()
    return hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()


def dedupe_candidates(candidates: Iterable[ImageCandidate], max_images: int) -> List[ImageCandidate]:
    by_key: Dict[str, ImageCandidate] = {}
    for candidate in candidates:
        if not candidate.image_url:
            continue
        key = canonical_image_key(candidate)
        existing = by_key.get(key)
        if not existing:
            by_key[key] = candidate
            continue
        if image_quality_score(candidate.image_url) > image_quality_score(existing.image_url):
            candidate.fallback_urls = unique_list([existing.image_url] + existing.fallback_urls + candidate.fallback_urls)
            by_key[key] = candidate
        elif candidate.detail_url and not existing.detail_url:
            existing.detail_url = candidate.detail_url
    result = list(by_key.values())
    if max_images > 0:
        result = result[:max_images]
    return result


def unique_list(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    seen: Set[str] = set()
    for value in values:
        if value and value not in seen:
            result.append(value)
            seen.add(value)
    return result


def normalize_start_url(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if not re.match(r"^[a-z][a-z0-9+.-]*://", text, re.IGNORECASE):
        text = "https://" + text.lstrip("/")
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = parsed.path or "/"
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def pinterest_search_url(keyword: str) -> str:
    text = clean_text(keyword, 120).strip().strip("#")
    if not text:
        return ""
    return normalize_start_url(
        "https://www.pinterest.com/search/pins/?q={}".format(quote(text, safe=""))
    )


def min_nonzero(first: int, second: int) -> int:
    values = [value for value in (first, second) if value > 0]
    return min(values) if values else 0


def detect_login_gate(page: object) -> Dict[str, object]:
    return page.evaluate(
        """() => {
            const isVisible = (el) => {
                const style = window.getComputedStyle(el);
                const rect = el.getBoundingClientRect();
                return style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    rect.width > 1 &&
                    rect.height > 1;
            };
            const inputs = Array.from(document.querySelectorAll('input')).filter(isVisible);
            const passwordCount = inputs.filter((input) =>
                (input.type || '').toLowerCase() === 'password'
            ).length;
            const accountCount = inputs.filter((input) => {
                const type = (input.type || '').toLowerCase();
                const name = (input.name || '').toLowerCase();
                const autocomplete = (input.autocomplete || '').toLowerCase();
                const placeholder = (input.placeholder || '').toLowerCase();
                return type === 'email' ||
                    name.includes('email') ||
                    autocomplete.includes('username') ||
                    placeholder.includes('email') ||
                    placeholder.includes('邮箱') ||
                    placeholder.includes('电子邮件') ||
                    placeholder.includes('手机号');
            }).length;
            const bodyText = (document.body ? document.body.innerText : '').toLowerCase();
            const url = location.href.toLowerCase();
            const title = (document.title || '').toLowerCase();
            const loginWords = [
                'log in',
                'login',
                'sign up',
                '登录',
                '登入',
                '注册',
                '继续使用',
                '使用账号'
            ];
            const hasLoginWords = loginWords.some((word) => bodyText.includes(word));
            const challengeWords = [
                'captcha',
                'verify you are human',
                'security check',
                'two-factor',
                'two factor authentication',
                'verification code',
                'unusual activity',
                'suspicious activity',
                'risk control',
                '验证码',
                '人机验证',
                '安全验证',
                '二次验证',
                '双重验证',
                '身份验证',
                '异常活动',
                '风控',
                '访问受限'
            ];
            const challengeUrlParts = [
                '/challenge', '/checkpoint', '/captcha', '/verify', '/security-check'
            ];
            const hasChallengeWords = challengeWords.some((word) =>
                bodyText.includes(word) || title.includes(word)
            );
            const hasChallengeFrame = Array.from(document.querySelectorAll('iframe')).some((frame) => {
                const source = (frame.src || '').toLowerCase();
                return source.includes('captcha') || source.includes('recaptcha') || source.includes('hcaptcha');
            });
            const hasChallengeUrl = challengeUrlParts.some((part) => url.includes(part));
            return {
                gated: passwordCount > 0 ||
                    url.includes('/login') ||
                    url.includes('/signup') ||
                    (accountCount > 0 && hasLoginWords) ||
                    hasChallengeWords ||
                    hasChallengeFrame ||
                    hasChallengeUrl,
                passwordCount,
                accountCount,
                hasChallengeWords,
                hasChallengeFrame,
                hasChallengeUrl,
                url,
                title: document.title || ''
            };
        }"""
    )


def first_visible_locator(page: object, selectors: Sequence[str], timeout_ms: int = 800) -> Optional[object]:
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 8)
            for index in range(count):
                item = locator.nth(index)
                try:
                    if item.is_visible(timeout=timeout_ms):
                        return item
                except Exception:
                    continue
        except Exception:
            continue
    return None


def open_login_form_if_available(page: object, log: LogFn) -> bool:
    login_button = first_visible_locator(
        page,
        [
            '[data-test-id="login-button"]',
            'button:has-text("Log in")',
            'button:has-text("Login")',
            'button:has-text("登录")',
            'button:has-text("登入")',
            'a:has-text("Log in")',
            'a:has-text("Login")',
            'a:has-text("登录")',
            'a:has-text("登入")',
        ],
        timeout_ms=500,
    )
    if not login_button:
        return False
    try:
        login_button.click(timeout=3_000)
        time.sleep(1.5)
        log("Login button clicked; looking for the form.")
        return True
    except Exception as exc:
        log("Login button click failed; continuing: {}".format(exc))
        return False


def attempt_auto_login(page: object, email: str, password: str, log: LogFn) -> bool:
    if not email or not password:
        return False

    email_input = first_visible_locator(
        page,
        [
            'input#email',
            'input[name="email"]',
            'input[type="email"]',
            'input[name="id"]',
            'input[autocomplete="username"]',
            'input[autocomplete="email"]',
            'input[aria-label*="email" i]',
            'input[aria-label*="邮箱" i]',
            'input[placeholder*="email" i]',
            'input[placeholder*="邮箱" i]',
        ],
    )
    password_input = first_visible_locator(
        page,
        [
            'input#password',
            'input[name="password"]',
            'input[type="password"]',
            'input[autocomplete="current-password"]',
            'input[aria-label*="password" i]',
            'input[aria-label*="密码" i]',
            'input[placeholder*="password" i]',
            'input[placeholder*="密码" i]',
        ],
    )
    if not email_input or not password_input:
        opened = open_login_form_if_available(page, log)
        if opened:
            email_input = first_visible_locator(
                page,
                [
                    'input#email',
                    'input[name="email"]',
                    'input[type="email"]',
                    'input[name="id"]',
                    'input[autocomplete="username"]',
                    'input[autocomplete="email"]',
                    'input[aria-label*="email" i]',
                    'input[aria-label*="邮箱" i]',
                    'input[placeholder*="email" i]',
                    'input[placeholder*="邮箱" i]',
                ],
            )
            password_input = first_visible_locator(
                page,
                [
                    'input#password',
                    'input[name="password"]',
                    'input[type="password"]',
                    'input[autocomplete="current-password"]',
                    'input[aria-label*="password" i]',
                    'input[aria-label*="密码" i]',
                    'input[placeholder*="password" i]',
                    'input[placeholder*="密码" i]',
                ],
            )
    if not email_input or not password_input:
        log("Login form detected, but matching email/password inputs were not found.")
        return False

    try:
        email_input.fill(email, timeout=5_000)
        password_input.fill(password, timeout=5_000)
        submit = first_visible_locator(
            page,
            [
                '[data-test-id="login-button"]',
                'button[type="submit"]',
                'button:has-text("Log in")',
                'button:has-text("Login")',
                'button:has-text("登录")',
                'button:has-text("登入")',
                'button:has-text("继续")',
            ],
        )
        if submit:
            submit.click(timeout=5_000)
        else:
            password_input.press("Enter", timeout=5_000)
        log("Login credentials submitted.")
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass
        time.sleep(2)
        return True
    except Exception as exc:
        log("Auto login failed before submit: {}".format(exc))
        return False


def wait_for_login_if_needed(
    page: object,
    timeout_seconds: int,
    login_email: str,
    login_password: str,
    log: LogFn,
    stop_event: Optional[threading.Event] = None,
    fail_on_login_gate: bool = False,
) -> None:
    time.sleep(1.5)
    try:
        state = detect_login_gate(page)
    except Exception as exc:
        raise LoginGateError("Login/CAPTCHA/2FA/risk-control detection failed") from exc
    if not state.get("gated"):
        return

    if fail_on_login_gate:
        raise LoginGateError(
            "Login, CAPTCHA, 2FA, or platform risk-control gate detected; "
            "non-interactive collection stopped"
        )

    if timeout_seconds <= 0:
        raise LoginGateError(
            "Login, CAPTCHA, 2FA, or platform risk-control gate remains active; collection stopped"
        )

    if login_email and login_password:
        log("Login form detected. Trying automatic login.")
        attempt_auto_login(page, login_email, login_password, log)
    else:
        log("Login form detected. Waiting up to {}s; finish login in the browser window.".format(timeout_seconds))

    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if stop_event and stop_event.is_set():
            return
        time.sleep(2)
        try:
            state = detect_login_gate(page)
        except Exception as exc:
            raise LoginGateError("Login/CAPTCHA/2FA/risk-control detection failed") from exc
        if not state.get("gated"):
            try:
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:
                pass
            log("Login gate cleared; collection continues.")
            return
    raise LoginGateError(
        "Login, CAPTCHA, 2FA, or platform risk-control gate was not cleared before timeout"
    )


def collect_from_browser(
    config: CollectorConfig,
    *,
    seed_detail_urls: Sequence[str],
    log: LogFn,
    stop_event: Optional[threading.Event] = None,
    download_index: Optional[DownloadIndex] = None,
) -> Tuple[List[ImageCandidate], List[str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Browser mode needs Playwright. Install it with:\n"
            "  python -m pip install playwright\n"
            "  python -m playwright install chromium"
        ) from exc

    if not config.start_urls:
        raise ValueError("At least one start URL is required.")

    candidates_by_key: Dict[str, ImageCandidate] = {}
    detail_queue: List[str] = []
    queued_detail_urls: Set[str] = set()
    visited_detail_urls: Set[str] = set()
    if download_index is None:
        download_index = load_download_index(
            collector_reference_dirs(config),
            max_bytes=config.max_download_bytes,
            max_pixels=config.max_image_pixels,
        )
    incremental_downloaded_keys: Set[str] = set(download_index.candidate_keys)

    def download_page_candidates(items: Iterable[ImageCandidate], page_label: str) -> None:
        """Download this page's images immediately, then allow the crawler to continue."""
        if not config.download_images:
            return
        page_candidates = dedupe_candidates(items, max_images=0)
        todo: List[ImageCandidate] = []
        for candidate in page_candidates:
            key = canonical_image_key(candidate)
            if key in incremental_downloaded_keys:
                continue
            todo.append(candidate)
            incremental_downloaded_keys.add(key)
        if not todo:
            log("  {} has no new images to download.".format(page_label))
            return
        log("  downloading {} images from {} before continuing.".format(len(todo), page_label))
        page_results = download_candidates(
            todo,
            config,
            log=log,
            stop_event=stop_event,
            reset_manifest=False,
            known_sha256_paths=download_index.sha256_paths,
        )
        for result in page_results:
            if result.ok:
                download_index.candidate_keys.add(
                    canonical_image_key(ImageCandidate(image_url=result.image_url))
                )

    def add_candidates(items: Iterable[ImageCandidate]) -> int:
        added = 0
        for candidate in items:
            key = canonical_image_key(candidate)
            # A scheduled incremental run must count only genuinely new URLs
            # towards max_images. Otherwise the first page can exhaust the
            # quota with entries that the manifest already completed.
            if key in download_index.candidate_keys:
                continue
            existing = candidates_by_key.get(key)
            if not existing:
                candidates_by_key[key] = candidate
                added += 1
                continue
            if image_quality_score(candidate.image_url) > image_quality_score(existing.image_url):
                candidate.fallback_urls = unique_list(
                    [existing.image_url] + existing.fallback_urls + candidate.fallback_urls
                )
                candidates_by_key[key] = candidate
            elif candidate.detail_url and not existing.detail_url:
                existing.detail_url = candidate.detail_url
        return added

    def enqueue_details(urls: Iterable[str]) -> int:
        added = 0
        for url in urls:
            detail_url = normalize_detail_url(url)
            if not detail_url:
                continue
            if detail_url in visited_detail_urls or detail_url in queued_detail_urls:
                continue
            detail_queue.append(detail_url)
            queued_detail_urls.add(detail_url)
            added += 1
        return added

    def reached_global_limit() -> bool:
        return config.max_images > 0 and len(candidates_by_key) >= config.max_images

    def remaining_global_images() -> int:
        if config.max_images <= 0:
            return max(0, config.detail_target_images)
        return max(0, config.max_images - len(candidates_by_key))

    enqueue_details(seed_detail_urls)
    config.browser_profile.mkdir(parents=True, exist_ok=True)

    browser_mode = "headless" if config.headless else "visible"
    log("Opening {} browser. Login will be attempted automatically when credentials are provided.".format(browser_mode))
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.browser_profile),
            headless=config.headless,
            viewport={"width": 1365, "height": 900},
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            for start_url in config.start_urls:
                if stop_event and stop_event.is_set():
                    break
                log("Loading start URL: {}".format(start_url))
                page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)
                wait_for_login_if_needed(
                    page,
                    config.login_wait_seconds,
                    config.login_email,
                    config.login_password,
                    log,
                    stop_event,
                    config.fail_on_login_gate,
                )
                start_detail_url = normalize_detail_url(start_url)
                if start_detail_url:
                    visited_detail_urls.add(start_detail_url)
                scroll_candidates, scroll_details = collect_scrolling_page(
                    page,
                    max_scrolls=config.detail_scrolls if start_detail_url else config.max_scrolls,
                    pause=config.scroll_pause,
                    upgrade_original=config.upgrade_original,
                    pinimg_only=config.pinimg_only,
                    target_new_images=min_nonzero(config.detail_target_images, remaining_global_images()) if start_detail_url else 0,
                    known_keys=set(candidates_by_key),
                    log=log,
                    stop_event=stop_event,
                )
                wait_for_login_if_needed(
                    page,
                    config.login_wait_seconds,
                    config.login_email,
                    config.login_password,
                    log,
                    stop_event,
                    config.fail_on_login_gate,
                )
                added = add_candidates(scroll_candidates)
                enqueued = enqueue_details(scroll_details)
                if start_detail_url:
                    download_page_candidates(scroll_candidates, "start detail page")
                log("  page added {} new images, queued {} new detail pages.".format(added, enqueued))
                if reached_global_limit():
                    log("Global image target reached.")
                    break

            if config.detail_pages > 0 and not (stop_event and stop_event.is_set()) and not reached_global_limit():
                log("Auto-visiting up to {} queued detail pages.".format(config.detail_pages))
                visited_count = 0
                while detail_queue and visited_count < config.detail_pages and not reached_global_limit():
                    if stop_event and stop_event.is_set():
                        break
                    detail_url = detail_queue.pop(0)
                    queued_detail_urls.discard(detail_url)
                    if detail_url in visited_detail_urls:
                        continue
                    visited_detail_urls.add(detail_url)
                    visited_count += 1
                    try:
                        log("Detail {}/{}: {}".format(visited_count, config.detail_pages, detail_url))
                        page.goto(detail_url, wait_until="domcontentloaded", timeout=60_000)
                        wait_for_login_if_needed(
                            page,
                            config.login_wait_seconds,
                            config.login_email,
                            config.login_password,
                            log,
                            stop_event,
                            config.fail_on_login_gate,
                        )
                        target_new_images = min_nonzero(config.detail_target_images, remaining_global_images())
                        detail_candidates, nested_details = collect_scrolling_page(
                            page,
                            max_scrolls=config.detail_scrolls,
                            pause=config.scroll_pause,
                            upgrade_original=config.upgrade_original,
                            pinimg_only=config.pinimg_only,
                            target_new_images=target_new_images,
                            known_keys=set(candidates_by_key),
                            log=log,
                            stop_event=stop_event,
                        )
                        wait_for_login_if_needed(
                            page,
                            config.login_wait_seconds,
                            config.login_email,
                            config.login_password,
                            log,
                            stop_event,
                            config.fail_on_login_gate,
                        )
                        for item in detail_candidates:
                            if not item.detail_url:
                                item.detail_url = detail_url
                        added = add_candidates(detail_candidates)
                        enqueued = enqueue_details(nested_details)
                        download_page_candidates(detail_candidates, "detail {}/{}".format(visited_count, config.detail_pages))
                        log("  detail added {} new images, queued {} more detail pages.".format(added, enqueued))
                    except LoginGateError:
                        raise
                    except Exception as exc:
                        log("  detail failed: {}".format(exc))
        finally:
            context.close()

    all_detail_urls = unique_list(list(visited_detail_urls) + detail_queue)
    return list(candidates_by_key.values()), all_detail_urls


def collect_scrolling_page(
    page: object,
    *,
    max_scrolls: int,
    pause: float,
    upgrade_original: bool,
    pinimg_only: bool,
    target_new_images: int = 0,
    known_keys: Optional[Set[str]] = None,
    log: LogFn,
    stop_event: Optional[threading.Event] = None,
) -> Tuple[List[ImageCandidate], List[str]]:
    candidates: List[ImageCandidate] = []
    detail_urls: List[str] = []
    known_keys = set(known_keys or set())
    stable_rounds = 0
    last_new_count = 0
    total_rounds = max(0, max_scrolls) + 1

    for round_index in range(total_rounds):
        if stop_event and stop_event.is_set():
            break
        dom_data = page.evaluate(
            """() => {
                const images = Array.from(document.images).map((img) => {
                    const anchor = img.closest('a[href]');
                    return {
                        src: img.currentSrc || img.src || '',
                        srcset: img.srcset || '',
                        alt: img.alt || '',
                        width: img.naturalWidth || img.width || null,
                        height: img.naturalHeight || img.height || null,
                        detail: anchor ? anchor.href : ''
                    };
                });
                const sources = Array.from(document.querySelectorAll('source[srcset], link[as="image"]')).map((node) => ({
                    src: node.getAttribute('href') || '',
                    srcset: node.getAttribute('srcset') || node.getAttribute('imagesrcset') || '',
                    alt: '',
                    width: null,
                    height: null,
                    detail: ''
                }));
                const anchors = Array.from(document.querySelectorAll('a[href]')).map((a) => a.href);
                return {url: location.href, title: document.title, images, sources, anchors, height: document.body.scrollHeight};
            }"""
        )
        page_candidates, page_details = candidates_from_dom(
            dom_data,
            upgrade_original=upgrade_original,
            pinimg_only=pinimg_only,
        )
        candidates.extend(page_candidates)
        detail_urls.extend(page_details)
        deduped_candidates = dedupe_candidates(candidates, max_images=0)
        deduped_now = len(deduped_candidates)
        new_count = sum(1 for candidate in deduped_candidates if canonical_image_key(candidate) not in known_keys)
        if target_new_images > 0:
            log("  scroll {}/{}: {} page candidates, {} new toward target {}".format(
                round_index + 1,
                total_rounds,
                deduped_now,
                new_count,
                target_new_images,
            ))
        else:
            log("  scroll {}/{}: {} unique candidates".format(round_index + 1, total_rounds, deduped_now))

        if target_new_images > 0 and new_count >= target_new_images:
            log("  page target reached.")
            break
        if new_count == last_new_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        last_new_count = new_count
        if stable_rounds >= 4:
            log("  page stopped yielding new images.")
            break
        if round_index < total_rounds - 1:
            page.mouse.wheel(0, 2800)
            time.sleep(max(0.2, pause))

    return dedupe_candidates(candidates, max_images=0), unique_list(detail_urls)


def candidates_from_dom(
    dom_data: Dict[str, object],
    *,
    upgrade_original: bool,
    pinimg_only: bool,
) -> Tuple[List[ImageCandidate], List[str]]:
    source_page = str(dom_data.get("url") or "")
    candidates: List[ImageCandidate] = []
    for item in list(dom_data.get("images") or []) + list(dom_data.get("sources") or []):
        if not isinstance(item, dict):
            continue
        urls: List[str] = []
        urls.extend(parse_srcset(str(item.get("srcset") or ""), source_page))
        src = normalize_url(str(item.get("src") or ""), source_page)
        if src:
            urls.append(src)
        primary, fallbacks = choose_primary_image_url(urls, upgrade_original)
        if not primary or not allowed_image_url(primary, pinimg_only):
            continue
        candidates.append(
            ImageCandidate(
                image_url=primary,
                source_page=source_page,
                detail_url=normalize_detail_url(str(item.get("detail") or ""), source_page),
                alt=clean_text(str(item.get("alt") or "")),
                width=parse_int(item.get("width")),
                height=parse_int(item.get("height")),
                source_kind="browser-dom",
                fallback_urls=[url for url in fallbacks if url != primary],
            )
        )

    detail_urls: List[str] = []
    for href in dom_data.get("anchors") or []:
        detail_url = normalize_detail_url(str(href), source_page)
        if detail_url:
            detail_urls.append(detail_url)
    return candidates, unique_list(detail_urls)


def write_jsonl(path: Path, rows: Iterable[object]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            if hasattr(row, "__dataclass_fields__"):
                payload = asdict(row)
            else:
                payload = row
            output.write(json.dumps(payload, ensure_ascii=False) + "\n")
            count += 1
    return count


def append_jsonl(path: Path, row: object) -> None:
    payload = asdict(row) if hasattr(row, "__dataclass_fields__") else row
    with path.open("a", encoding="utf-8") as output:
        output.write(json.dumps(payload, ensure_ascii=False) + "\n")


def unique_paths(values: Iterable[Path]) -> List[Path]:
    result: List[Path] = []
    seen: Set[str] = set()
    for value in values:
        try:
            normalized = str(Path(value).resolve()).lower()
        except OSError:
            normalized = str(Path(value).absolute()).lower()
        if normalized in seen:
            continue
        result.append(Path(value))
        seen.add(normalized)
    return result


def collector_reference_dirs(config: CollectorConfig) -> List[Path]:
    return unique_paths([config.output_dir] + list(config.dedupe_reference_dirs or []))


def load_download_index(
    reference_dirs: Iterable[Path],
    *,
    max_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    max_pixels: int = DEFAULT_MAX_IMAGE_PIXELS,
) -> DownloadIndex:
    """Load manifest history while trusting only verified local image files."""
    index = DownloadIndex()
    validation_cache: Dict[Tuple[str, str], bool] = {}
    for reference_dir in unique_paths(Path(path) for path in reference_dirs):
        manifest_path = reference_dir / "manifest.jsonl"
        if not manifest_path.exists():
            continue
        try:
            with manifest_path.open("r", encoding="utf-8") as input_file:
                for line in input_file:
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    image_url = str(row.get("image_url") or "")
                    if image_url:
                        index.seen_candidate_keys.add(
                            canonical_image_key(ImageCandidate(image_url=image_url))
                        )
                    if not row.get("ok"):
                        continue
                    digest = str(row.get("sha256") or "")
                    local_path = str(row.get("local_path") or "")
                    if not image_url or not digest or not local_path:
                        continue
                    cache_key = (str(Path(local_path).absolute()), digest)
                    valid = validation_cache.get(cache_key)
                    if valid is None:
                        valid = existing_download_matches(
                            Path(local_path),
                            digest,
                            max_bytes,
                            max_pixels,
                        )
                        validation_cache[cache_key] = valid
                    if not valid:
                        continue
                    index.candidate_keys.add(
                        canonical_image_key(ImageCandidate(image_url=image_url))
                    )
                    index.sha256_paths.setdefault(digest, local_path)
        except OSError:
            continue
    return index


def load_completed_candidate_keys(manifest_path: Path) -> Set[str]:
    """Load successful downloads from an existing manifest for resume support."""
    return load_download_index([manifest_path.parent]).candidate_keys


def extension_from_url(url: str) -> str:
    suffix = Path(urlparse(url).path.lower()).suffix
    if suffix in IMAGE_EXTENSIONS:
        return ".jpg" if suffix == ".jpeg" else suffix
    guessed = mimetypes.guess_extension(url) or ".jpg"
    return ".jpg" if guessed == ".jpe" else guessed


def extension_from_content_type(content_type: str, fallback: str) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if ctype == "image/jpeg":
        return ".jpg"
    guessed = mimetypes.guess_extension(ctype) if ctype else None
    if guessed in IMAGE_EXTENSIONS:
        return ".jpg" if guessed == ".jpeg" else guessed
    return fallback


def download_candidates(
    candidates: Sequence[ImageCandidate],
    config: CollectorConfig,
    *,
    log: LogFn,
    stop_event: Optional[threading.Event] = None,
    reset_manifest: bool = False,
    known_sha256_paths: Optional[Dict[str, str]] = None,
) -> List[DownloadResult]:
    images_dir = config.output_dir / "images"
    manifest_path = config.output_dir / "manifest.jsonl"
    images_dir.mkdir(parents=True, exist_ok=True)
    if reset_manifest and manifest_path.exists():
        manifest_path.unlink()

    if not config.download_images:
        log("Download disabled; only candidates.jsonl was written.")
        return []

    log("Downloading {} images with {} worker(s).".format(len(candidates), config.workers))
    results: List[DownloadResult] = []
    sha256_paths = known_sha256_paths if known_sha256_paths is not None else {}
    sha256_snapshot = dict(sha256_paths)
    workers = max(1, min(16, int(config.workers or 1)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(download_one, index, candidate, images_dir, config, sha256_snapshot): (index, candidate)
            for index, candidate in enumerate(candidates, start=1)
        }
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            if stop_event and stop_event.is_set():
                break
            try:
                result = future.result()
            except Exception as exc:
                index, candidate = futures[future]
                result = DownloadResult(
                    ok=False,
                    status="error",
                    image_url=candidate.image_url,
                    source_page=candidate.source_page,
                    detail_url=candidate.detail_url,
                    alt=candidate.alt,
                    width=candidate.width,
                    height=candidate.height,
                    error=str(exc),
                    downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                )
            results.append(result)
            append_jsonl(manifest_path, result)
            if result.ok and result.sha256:
                sha256_paths.setdefault(result.sha256, result.local_path)
            if result.ok:
                log("  [{}/{}] saved {}".format(completed, len(candidates), result.local_path))
            else:
                log("  [{}/{}] {} {}".format(completed, len(candidates), result.status, result.error))
    return results


def download_one(
    index: int,
    candidate: ImageCandidate,
    images_dir: Path,
    config: CollectorConfig,
    known_sha256_paths: Dict[str, str],
) -> DownloadResult:
    if config.request_delay > 0:
        time.sleep(config.request_delay * ((index - 1) % max(1, config.workers)))

    urls = unique_list([candidate.image_url] + candidate.fallback_urls)
    errors: List[str] = []
    for url in urls:
        try:
            if not allowed_image_url(url, config.pinimg_only):
                raise ValueError("disallowed image URL: {}".format(url))
            headers = dict(DEFAULT_HEADERS)
            if candidate.source_page.startswith("http"):
                headers["Referer"] = candidate.source_page
            request = Request(url, headers=headers)
            with urlopen(request, timeout=45) as response:
                final_url = response.geturl()
                if not allowed_image_url(final_url, config.pinimg_only):
                    raise ValueError(
                        "redirected to disallowed image URL: {}".format(final_url)
                    )
                content_type = response.headers.get("Content-Type", "")
                data = read_response_limited(response, config.max_download_bytes)
            if not data:
                raise ValueError("empty response")
            if content_type and not content_type.lower().startswith("image/"):
                raise ValueError("not an image content-type: {}".format(content_type))
            actual_width, actual_height, detected_content_type = validate_downloaded_image(
                data,
                config.max_image_pixels,
            )
            content_type = detected_content_type
            digest = hashlib.sha256(data).hexdigest()
            ext = extension_from_content_type(content_type, extension_from_url(url))
            local_path = images_dir / "{}{}".format(digest[:20], ext)
            already_exists = local_path.exists() or local_path.is_symlink()
            if local_path.is_symlink():
                raise ValueError("existing download path must not be a symlink: {}".format(local_path))
            if already_exists and not local_path.is_file():
                raise ValueError("existing download path is not a regular file: {}".format(local_path))
            existing_is_valid = already_exists and existing_download_matches(
                local_path,
                digest,
                config.max_download_bytes,
                config.max_image_pixels,
            )
            reference_path = known_sha256_paths.get(digest, "")
            if not already_exists and reference_path and existing_download_matches(
                Path(reference_path),
                digest,
                config.max_download_bytes,
                config.max_image_pixels,
            ):
                return DownloadResult(
                    ok=True,
                    status="duplicate-content",
                    image_url=url,
                    local_path=reference_path,
                    source_page=candidate.source_page,
                    detail_url=candidate.detail_url,
                    alt=candidate.alt,
                    width=actual_width,
                    height=actual_height,
                    bytes=len(data),
                    sha256=digest,
                    content_type=content_type,
                    downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                )
            if not existing_is_valid:
                atomic_write_download(local_path, data)
            return DownloadResult(
                ok=True,
                status="exists" if existing_is_valid else ("repaired" if already_exists else "downloaded"),
                image_url=url,
                local_path=str(local_path),
                source_page=candidate.source_page,
                detail_url=candidate.detail_url,
                alt=candidate.alt,
                width=actual_width,
                height=actual_height,
                bytes=len(data),
                sha256=digest,
                content_type=content_type,
                downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(),
            )
        except (HTTPError, URLError, OSError, ValueError) as exc:
            errors.append("{}: {}".format(url, exc))
            continue
    return DownloadResult(
        ok=False,
        status="failed",
        image_url=candidate.image_url,
        source_page=candidate.source_page,
        detail_url=candidate.detail_url,
        alt=candidate.alt,
        width=candidate.width,
        height=candidate.height,
        error="; ".join(errors[-3:]),
        downloaded_at=dt.datetime.now(dt.timezone.utc).isoformat(),
    )


def read_response_limited(response: object, max_bytes: int) -> bytes:
    """Read one HTTP response without allowing an unbounded in-memory body."""
    if max_bytes <= 0:
        raise ValueError("max download bytes must be positive")
    headers = getattr(response, "headers", {}) or {}
    raw_length = headers.get("Content-Length", "") if hasattr(headers, "get") else ""
    if raw_length:
        try:
            content_length = int(str(raw_length).strip())
        except ValueError as exc:
            raise ValueError("invalid Content-Length: {}".format(raw_length)) from exc
        if content_length < 0 or content_length > max_bytes:
            raise ValueError("image response exceeds {} bytes".format(max_bytes))

    payload = bytearray()
    while True:
        remaining_with_sentinel = max_bytes - len(payload) + 1
        chunk = response.read(min(DOWNLOAD_CHUNK_BYTES, remaining_with_sentinel))
        if not chunk:
            break
        payload.extend(chunk)
        if len(payload) > max_bytes:
            raise ValueError("image response exceeds {} bytes".format(max_bytes))
    return bytes(payload)


def validate_downloaded_image(data: bytes, max_pixels: int) -> Tuple[int, int, str]:
    """Verify image structure and reject oversized decoded images before writing."""
    if max_pixels <= 0:
        raise ValueError("max image pixels must be positive")
    try:
        from PIL import Image
    except ImportError as exc:
        raise ValueError("Pillow is required to validate downloaded images") from exc
    with Image.open(io.BytesIO(data)) as image:
        image_format = str(image.format or "").upper()
        if image_format not in IMAGE_FORMAT_MIME_TYPES:
            raise ValueError("unsupported image format: {}".format(image_format or "unknown"))
        width, height = image.size
        if width <= 0 or height <= 0 or width * height > max_pixels:
            raise ValueError(
                "decoded image dimensions {}x{} exceed {} pixels".format(width, height, max_pixels)
            )
        image.verify()
    return int(width), int(height), IMAGE_FORMAT_MIME_TYPES[image_format]


def existing_download_matches(
    path: Path,
    expected_sha256: str,
    max_bytes: int,
    max_pixels: int,
) -> bool:
    """Verify an existing regular file before treating it as a completed download."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        size = path.stat().st_size
        if size <= 0 or size > max_bytes:
            return False
        with path.open("rb") as input_file:
            payload = input_file.read(max_bytes + 1)
        if len(payload) != size or hashlib.sha256(payload).hexdigest() != expected_sha256:
            return False
        validate_downloaded_image(payload, max_pixels)
        return True
    except (OSError, ValueError):
        return False


def atomic_write_download(path: Path, data: bytes) -> None:
    """Durably write one image through a same-directory temporary and atomic rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".{}.".format(path.name),
        suffix=".tmp",
        dir=str(path.parent),
    )
    descriptor_open = True
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            descriptor_open = False
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(str(temporary), str(path))
        if os.name == "posix" and hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if descriptor_open:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def run_collection(
    config: CollectorConfig,
    *,
    log: LogFn = print,
    stop_event: Optional[threading.Event] = None,
) -> Dict[str, int]:
    started_at = time.time()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    log("Output: {}".format(config.output_dir))
    reference_dirs = collector_reference_dirs(config)
    log("Dedupe references: {}".format(", ".join(str(path) for path in reference_dirs)))
    download_index = load_download_index(
        reference_dirs,
        max_bytes=config.max_download_bytes,
        max_pixels=config.max_image_pixels,
    )

    all_candidates, detail_urls = collect_from_browser(
        config,
        seed_detail_urls=[],
        log=log,
        stop_event=stop_event,
        download_index=download_index,
    )

    deduped = dedupe_candidates(all_candidates, config.max_images)
    write_jsonl(config.output_dir / "candidates.jsonl", deduped)
    write_jsonl(config.output_dir / "detail_urls.jsonl", [{"url": url} for url in unique_list(detail_urls)])
    log("Collected {} unique image candidates.".format(len(deduped)))
    log("Collected {} unique detail URLs.".format(len(unique_list(detail_urls))))

    completed_keys = download_index.candidate_keys
    remaining = [
        candidate for candidate in deduped
        if canonical_image_key(candidate) not in completed_keys
    ]
    if remaining:
        log("Downloading {} remaining images that were not downloaded during detail-page visits.".format(len(remaining)))
    results = download_candidates(
        remaining,
        config,
        log=log,
        stop_event=stop_event,
        reset_manifest=False,
        known_sha256_paths=download_index.sha256_paths,
    )
    for result in results:
        if result.ok:
            download_index.candidate_keys.add(
                canonical_image_key(ImageCandidate(image_url=result.image_url))
            )
    current_keys = load_download_index(
        [config.output_dir],
        max_bytes=config.max_download_bytes,
        max_pixels=config.max_image_pixels,
    ).candidate_keys
    known_keys = download_index.candidate_keys
    ok_count = len(current_keys)
    failed_count = sum(1 for result in results if not result.ok)
    elapsed = int(time.time() - started_at)
    log("Done in {}s. saved={}, known_dedupe={}, failed={}.".format(elapsed, ok_count, len(known_keys), failed_count))
    return {
        "candidates": len(deduped),
        "details": len(unique_list(detail_urls)),
        "saved": ok_count,
        "failed": failed_count,
        "elapsed_seconds": elapsed,
    }


class DatasetCollectorApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title("RanGwaz Dataset Collector")
        self.root.geometry("900x720")
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: Optional[threading.Thread] = None

        self.output_dir_var = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.max_images_var = tk.StringVar(value=str(DEFAULT_TARGET_IMAGES))
        self.max_scrolls_var = tk.StringVar(value=str(DEFAULT_START_SCROLLS))
        self.detail_pages_var = tk.StringVar(value=str(DEFAULT_DETAIL_PAGES))
        self.detail_scrolls_var = tk.StringVar(value=str(DEFAULT_DETAIL_SCROLLS))
        self.detail_target_var = tk.StringVar(value=str(DEFAULT_DETAIL_TARGET_IMAGES))
        self.login_wait_var = tk.StringVar(value=str(DEFAULT_LOGIN_WAIT_SECONDS))
        self.login_email_var = tk.StringVar(value=os.environ.get("RANGWAZ_LOGIN_EMAIL", DEFAULT_LOGIN_EMAIL))
        self.login_password_var = tk.StringVar(value=os.environ.get("RANGWAZ_LOGIN_PASSWORD", DEFAULT_LOGIN_PASSWORD))
        self.workers_var = tk.StringVar(value=str(DEFAULT_DOWNLOAD_WORKERS))
        self.pause_var = tk.StringVar(value=str(DEFAULT_SCROLL_PAUSE))
        self.delay_var = tk.StringVar(value=str(DEFAULT_REQUEST_DELAY))
        self.download_var = tk.BooleanVar(value=True)
        self.upgrade_var = tk.BooleanVar(value=True)
        self.pinimg_only_var = tk.BooleanVar(value=True)

        self._build()
        self.root.after(100, self._drain_logs)

    def run(self) -> None:
        self.root.mainloop()

    def _build(self) -> None:
        tk = self.tk
        ttk = self.ttk
        pad = {"padx": 10, "pady": 6}

        frame = ttk.Frame(self.root)
        frame.pack(fill="both", expand=True)

        title = ttk.Label(frame, text="RanGwaz 数据集采集工具", font=("Microsoft YaHei UI", 16, "bold"))
        title.pack(anchor="w", padx=12, pady=(12, 4))

        form = ttk.Frame(frame)
        form.pack(fill="x", **pad)
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="输出目录").grid(row=0, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.output_dir_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(form, text="选择", command=self._choose_output).grid(row=0, column=2)

        ttk.Label(form, text="首页域名/入口URL，每行一个").grid(row=1, column=0, sticky="nw")
        self.urls_text = tk.Text(form, height=4, wrap="word")
        self.urls_text.grid(row=1, column=1, columnspan=2, sticky="ew", padx=8)

        ttk.Label(form, text="登录邮箱").grid(row=2, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.login_email_var).grid(row=2, column=1, columnspan=2, sticky="ew", padx=8)

        ttk.Label(form, text="登录密码").grid(row=3, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.login_password_var, show="*").grid(row=3, column=1, columnspan=2, sticky="ew", padx=8)

        options = ttk.LabelFrame(frame, text="采集选项")
        options.pack(fill="x", **pad)
        for column in range(6):
            options.columnconfigure(column, weight=1)

        self._option_entry(options, "最大图片", self.max_images_var, 0, 0)
        self._option_entry(options, "滚动次数", self.max_scrolls_var, 0, 2)
        self._option_entry(options, "详情页数", self.detail_pages_var, 0, 4)
        self._option_entry(options, "详情滚动", self.detail_scrolls_var, 1, 0)
        self._option_entry(options, "每详情目标", self.detail_target_var, 1, 2)
        self._option_entry(options, "登录等待秒", self.login_wait_var, 1, 4)
        self._option_entry(options, "下载线程", self.workers_var, 2, 0)
        self._option_entry(options, "滚动等待秒", self.pause_var, 2, 2)
        self._option_entry(options, "请求错峰秒", self.delay_var, 2, 4)

        ttk.Checkbutton(options, text="下载图片", variable=self.download_var).grid(row=3, column=4, sticky="w")
        ttk.Checkbutton(options, text="优先原图", variable=self.upgrade_var).grid(row=3, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(options, text="仅 i.pinimg.com 图片", variable=self.pinimg_only_var).grid(row=3, column=2, columnspan=2, sticky="w")

        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", **pad)
        self.start_button = ttk.Button(buttons, text="开始采集", command=self._start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="停止", command=self._stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)

        help_text = (
            "说明：本工具只使用可见浏览器滚动采集，不会绕过验证码或登录限制。"
            "提供账号密码时会自动填表登录；遇到验证码或二次验证时会等待你手动处理。"
        )
        ttk.Label(frame, text=help_text, wraplength=860).pack(fill="x", padx=12, pady=(0, 6))

        log_frame = ttk.LabelFrame(frame, text="日志")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _option_entry(self, parent: object, label: str, variable: object, row: int, col: int) -> None:
        ttk = self.ttk
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(8, 4), pady=6)
        ttk.Entry(parent, textvariable=variable, width=10).grid(row=row, column=col + 1, sticky="w", pady=6)

    def _choose_output(self) -> None:
        path = self.filedialog.askdirectory(initialdir=str(ROOT / "tools"))
        if path:
            self.output_dir_var.set(path)

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            config = self._read_config()
        except ValueError as exc:
            self.messagebox.showerror("配置错误", str(exc))
            return

        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._log("Starting...")

        def target() -> None:
            try:
                run_collection(config, log=self._log, stop_event=self.stop_event)
            except Exception:
                self._log(traceback.format_exc())
            finally:
                self.log_queue.put("__DONE__")

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        self._log("Stop requested; waiting for current work to finish.")

    def _read_config(self) -> CollectorConfig:
        urls = []
        for line in self.urls_text.get("1.0", "end").splitlines():
            normalized = normalize_start_url(line)
            if normalized:
                urls.append(normalized)
        if not urls:
            raise ValueError("请至少填写一个起始 URL")
        return CollectorConfig(
            output_dir=Path(self.output_dir_var.get().strip() or DEFAULT_OUTPUT_DIR),
            start_urls=urls,
            max_images=parse_positive_int(self.max_images_var.get(), "最大图片"),
            max_scrolls=parse_positive_int(self.max_scrolls_var.get(), "滚动次数"),
            detail_pages=parse_positive_int(self.detail_pages_var.get(), "详情页数"),
            detail_scrolls=parse_positive_int(self.detail_scrolls_var.get(), "详情滚动"),
            detail_target_images=parse_positive_int(self.detail_target_var.get(), "每详情目标"),
            login_wait_seconds=parse_positive_int(self.login_wait_var.get(), "登录等待秒"),
            login_email=self.login_email_var.get().strip(),
            login_password=self.login_password_var.get(),
            workers=parse_positive_int(self.workers_var.get(), "下载线程"),
            request_delay=parse_float(self.delay_var.get(), "请求错峰秒"),
            scroll_pause=parse_float(self.pause_var.get(), "滚动等待秒"),
            upgrade_original=bool(self.upgrade_var.get()),
            pinimg_only=bool(self.pinimg_only_var.get()),
            download_images=bool(self.download_var.get()),
        )

    def _log(self, message: str) -> None:
        self.log_queue.put(message)

    def _drain_logs(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if message == "__DONE__":
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                continue
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
        self.root.after(100, self._drain_logs)


class DatasetCollectorApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.root = tk.Tk()
        self.root.title("RanGwaz唯一QQ: 1309388631")
        self.root.geometry("1040x780")
        self.root.minsize(960, 700)
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.stop_event = threading.Event()
        self.worker: Optional[threading.Thread] = None
        self.title_color_index = 0
        self.title_colors = ["#ff604b", "#42c7b7", "#7c5cff", "#ffcf5a", "#38bdf8", "#fb7185"]

        self.output_dir_var = tk.StringVar(value=str(DEFAULT_OUTPUT_DIR))
        self.max_images_var = tk.StringVar(value=str(DEFAULT_TARGET_IMAGES))
        self.max_scrolls_var = tk.StringVar(value=str(DEFAULT_START_SCROLLS))
        self.detail_pages_var = tk.StringVar(value=str(DEFAULT_DETAIL_PAGES))
        self.detail_scrolls_var = tk.StringVar(value=str(DEFAULT_DETAIL_SCROLLS))
        self.detail_target_var = tk.StringVar(value=str(DEFAULT_DETAIL_TARGET_IMAGES))
        self.login_wait_var = tk.StringVar(value=str(DEFAULT_LOGIN_WAIT_SECONDS))
        self.login_email_var = tk.StringVar(value=os.environ.get("RANGWAZ_LOGIN_EMAIL", DEFAULT_LOGIN_EMAIL))
        self.login_password_var = tk.StringVar(value=os.environ.get("RANGWAZ_LOGIN_PASSWORD", DEFAULT_LOGIN_PASSWORD))
        self.workers_var = tk.StringVar(value=str(DEFAULT_DOWNLOAD_WORKERS))
        self.pause_var = tk.StringVar(value=str(DEFAULT_SCROLL_PAUSE))
        self.delay_var = tk.StringVar(value=str(DEFAULT_REQUEST_DELAY))
        self.download_var = tk.BooleanVar(value=True)
        self.upgrade_var = tk.BooleanVar(value=True)
        self.pinimg_only_var = tk.BooleanVar(value=True)

        self._configure_style()
        self._set_window_icon()
        self._build()
        self.root.after(100, self._drain_logs)
        self.root.after(300, self._animate_title)

    def run(self) -> None:
        self.root.mainloop()

    def _configure_style(self) -> None:
        style = self.ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("App.TFrame", background="#0f1220")
        style.configure("Panel.TFrame", background="#171b2c")
        style.configure("Card.TFrame", background="#171b2c")
        style.configure("Card.TLabel", background="#171b2c", foreground="#f8fafc", font=("Microsoft YaHei UI", 10))
        style.configure("CardTitle.TLabel", background="#171b2c", foreground="#f8fafc", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("TNotebook", background="#0f1220", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(18, 9), font=("Microsoft YaHei UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#ff604b")], foreground=[("selected", "#ffffff")])
        style.configure("Accent.TButton", font=("Microsoft YaHei UI", 11, "bold"), padding=(16, 9))
        style.configure("Ghost.TButton", font=("Microsoft YaHei UI", 10), padding=(12, 8))
        style.configure("TCheckbutton", background="#171b2c", foreground="#e5e7eb", font=("Microsoft YaHei UI", 10))
        style.map("TCheckbutton", background=[("active", "#171b2c")], foreground=[("active", "#ffffff")])

    def _set_window_icon(self) -> None:
        icon = self.tk.PhotoImage(width=64, height=64)
        icon.put("#0f1220", to=(0, 0, 64, 64))
        icon.put("#ff604b", to=(14, 10, 24, 54))
        icon.put("#ff604b", to=(24, 10, 42, 19))
        icon.put("#ff604b", to=(24, 29, 43, 38))
        icon.put("#ff604b", to=(42, 18, 50, 31))
        icon.put("#ff604b", to=(38, 38, 49, 54))
        icon.put("#42c7b7", to=(24, 19, 39, 29))
        self.window_icon = icon
        self.root.iconphoto(True, icon)

    def _build(self) -> None:
        tk = self.tk
        ttk = self.ttk
        shell = ttk.Frame(self.root, style="App.TFrame")
        shell.pack(fill="both", expand=True)

        header = tk.Frame(shell, bg="#0f1220")
        header.pack(fill="x", padx=18, pady=(16, 10))
        self.logo_canvas = tk.Canvas(header, width=58, height=58, bg="#0f1220", highlightthickness=0)
        self.logo_canvas.pack(side="left")
        self.logo_canvas.create_rectangle(5, 5, 53, 53, fill="#151a2d", outline="#2b3248", width=2)
        self.logo_canvas.create_text(29, 29, text="R", font=("Segoe UI Black", 30, "bold"), fill="#ff604b", tags=("logo_r",))

        title_box = tk.Frame(header, bg="#0f1220")
        title_box.pack(side="left", fill="x", expand=True, padx=16)
        self.title_label = tk.Label(
            title_box,
            text="RanGwaz唯一QQ: 1309388631",
            bg="#0f1220",
            fg="#ff604b",
            font=("Microsoft YaHei UI", 22, "bold"),
        )
        self.title_label.pack(anchor="w")
        tk.Label(
            title_box,
            text="Pinterest 入口 URL / 搜索关键词采集 · 自动进入详情页 · 跨批次去重",
            bg="#0f1220",
            fg="#aab3c5",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        actions = tk.Frame(header, bg="#0f1220")
        actions.pack(side="right")
        self.start_button = ttk.Button(actions, text="开始采集", style="Accent.TButton", command=self._start)
        self.start_button.pack(side="left", padx=(0, 8))
        self.stop_button = ttk.Button(actions, text="停止", style="Ghost.TButton", command=self._stop, state="disabled")
        self.stop_button.pack(side="left")

        notebook = ttk.Notebook(shell)
        notebook.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        entry_tab = ttk.Frame(notebook, style="Panel.TFrame")
        option_tab = ttk.Frame(notebook, style="Panel.TFrame")
        log_tab = ttk.Frame(notebook, style="Panel.TFrame")
        notebook.add(entry_tab, text="入口与关键词")
        notebook.add(option_tab, text="采集参数")
        notebook.add(log_tab, text="运行日志")
        self._build_entry_tab(entry_tab)
        self._build_option_tab(option_tab)
        self._build_log_tab(log_tab)

    def _build_entry_tab(self, parent: object) -> None:
        tk = self.tk
        ttk = self.ttk
        parent.columnconfigure(0, weight=1)
        self._section_title(parent, "输出目录", 0)
        row = self.tk.Frame(parent, bg="#171b2c")
        row.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        row.columnconfigure(0, weight=1)
        ttk.Entry(row, textvariable=self.output_dir_var).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(row, text="选择目录", style="Ghost.TButton", command=self._choose_output).grid(row=0, column=1)

        self._section_title(parent, "入口 URL，每行一个", 2)
        self.urls_text = tk.Text(parent, height=5, wrap="word", bg="#0b1020", fg="#f8fafc", insertbackground="#ff604b", relief="flat", padx=12, pady=10)
        self.urls_text.grid(row=3, column=0, sticky="nsew", padx=18, pady=(0, 14))

        self._section_title(parent, "搜索关键词 / 热门标签，每行一个", 4)
        self.keywords_text = tk.Text(parent, height=5, wrap="word", bg="#0b1020", fg="#f8fafc", insertbackground="#42c7b7", relief="flat", padx=12, pady=10)
        self.keywords_text.grid(row=5, column=0, sticky="nsew", padx=18, pady=(0, 10))

        hint = (
            "关键词会自动变成：https://www.pinterest.com/search/pins/?q=关键词。"
            " 可以只填关键词，也可以同时填入口 URL；例如 anime wallpaper、cyberpunk girl、minimal iphone wallpaper。"
            " 原有自动滚动、进入详情页、下载和去重逻辑全部复用。"
        )
        tk.Label(parent, text=hint, bg="#171b2c", fg="#aab3c5", wraplength=920, justify="left", font=("Microsoft YaHei UI", 10)).grid(
            row=6, column=0, sticky="ew", padx=18, pady=(0, 16)
        )
        parent.rowconfigure(3, weight=1)
        parent.rowconfigure(5, weight=1)

    def _build_option_tab(self, parent: object) -> None:
        ttk = self.ttk
        for col in range(6):
            parent.columnconfigure(col, weight=1)

        login = ttk.Frame(parent, style="Card.TFrame")
        login.grid(row=0, column=0, columnspan=6, sticky="ew", padx=18, pady=(18, 10))
        for col in range(6):
            login.columnconfigure(col, weight=1)
        ttk.Label(login, text="登录信息", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=6, sticky="w", padx=14, pady=(12, 8))
        self._field(login, "登录邮箱", self.login_email_var, 1, 0)
        self._field(login, "登录密码", self.login_password_var, 1, 2, show="*")
        self._field(login, "登录等待秒", self.login_wait_var, 1, 4)

        crawl = ttk.Frame(parent, style="Card.TFrame")
        crawl.grid(row=1, column=0, columnspan=6, sticky="ew", padx=18, pady=10)
        for col in range(6):
            crawl.columnconfigure(col, weight=1)
        ttk.Label(crawl, text="采集强度", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=6, sticky="w", padx=14, pady=(12, 8))
        self._field(crawl, "最大图片", self.max_images_var, 1, 0)
        self._field(crawl, "首页滚动", self.max_scrolls_var, 1, 2)
        self._field(crawl, "详情页数", self.detail_pages_var, 1, 4)
        self._field(crawl, "详情滚动", self.detail_scrolls_var, 2, 0)
        self._field(crawl, "每详情目标", self.detail_target_var, 2, 2)
        self._field(crawl, "滚动等待秒", self.pause_var, 2, 4)
        self._field(crawl, "下载线程", self.workers_var, 3, 0)
        self._field(crawl, "请求错峰秒", self.delay_var, 3, 2)

        switches = ttk.Frame(parent, style="Card.TFrame")
        switches.grid(row=2, column=0, columnspan=6, sticky="ew", padx=18, pady=10)
        ttk.Label(switches, text="下载与过滤", style="CardTitle.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", padx=14, pady=(12, 8))
        ttk.Checkbutton(switches, text="下载图片", variable=self.download_var).grid(row=1, column=0, sticky="w", padx=14, pady=(0, 14))
        ttk.Checkbutton(switches, text="优先原图", variable=self.upgrade_var).grid(row=1, column=1, sticky="w", padx=14, pady=(0, 14))
        ttk.Checkbutton(switches, text="仅 i.pinimg.com 图片", variable=self.pinimg_only_var).grid(row=1, column=2, sticky="w", padx=14, pady=(0, 14))

    def _build_log_tab(self, parent: object) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)
        self.tk.Label(parent, text="运行日志", bg="#171b2c", fg="#f8fafc", font=("Microsoft YaHei UI", 13, "bold")).grid(
            row=0, column=0, sticky="w", padx=18, pady=(18, 8)
        )
        self.log_text = self.tk.Text(parent, wrap="word", bg="#090d18", fg="#dbe4f0", insertbackground="#ff604b", relief="flat", padx=12, pady=12)
        self.log_text.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 18))

    def _section_title(self, parent: object, text: str, row: int) -> None:
        self.tk.Label(parent, text=text, bg="#171b2c", fg="#f8fafc", font=("Microsoft YaHei UI", 12, "bold")).grid(
            row=row, column=0, sticky="w", padx=18, pady=(18, 8)
        )

    def _field(self, parent: object, label: str, variable: object, row: int, col: int, show: str = "") -> None:
        self.ttk.Label(parent, text=label, style="Card.TLabel").grid(row=row, column=col, sticky="w", padx=(14, 8), pady=8)
        self.ttk.Entry(parent, textvariable=variable, show=show, width=18).grid(row=row, column=col + 1, sticky="ew", padx=(0, 14), pady=8)

    def _choose_output(self) -> None:
        path = self.filedialog.askdirectory(initialdir=str(ROOT / "tools"))
        if path:
            self.output_dir_var.set(path)

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            config = self._read_config()
        except ValueError as exc:
            self.messagebox.showerror("配置错误", str(exc))
            return

        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._log("Starting...")
        self._log("Start URLs:")
        for url in config.start_urls:
            self._log("  " + url)

        def target() -> None:
            try:
                run_collection(config, log=self._log, stop_event=self.stop_event)
            except Exception:
                self._log(traceback.format_exc())
            finally:
                self.log_queue.put("__DONE__")

        self.worker = threading.Thread(target=target, daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        self._log("Stop requested; waiting for current work to finish.")

    def _read_config(self) -> CollectorConfig:
        urls: List[str] = []
        for line in self.urls_text.get("1.0", "end").splitlines():
            normalized = normalize_start_url(line)
            if normalized:
                urls.append(normalized)
        for line in self.keywords_text.get("1.0", "end").splitlines():
            search_url = pinterest_search_url(line)
            if search_url:
                urls.append(search_url)
        urls = unique_list(urls)
        if not urls:
            raise ValueError("请至少填写一个入口 URL 或搜索关键词")
        return CollectorConfig(
            output_dir=Path(self.output_dir_var.get().strip() or DEFAULT_OUTPUT_DIR),
            start_urls=urls,
            max_images=parse_positive_int(self.max_images_var.get(), "最大图片"),
            max_scrolls=parse_positive_int(self.max_scrolls_var.get(), "首页滚动"),
            detail_pages=parse_positive_int(self.detail_pages_var.get(), "详情页数"),
            detail_scrolls=parse_positive_int(self.detail_scrolls_var.get(), "详情滚动"),
            detail_target_images=parse_positive_int(self.detail_target_var.get(), "每详情目标"),
            login_wait_seconds=parse_positive_int(self.login_wait_var.get(), "登录等待秒"),
            login_email=self.login_email_var.get().strip(),
            login_password=self.login_password_var.get(),
            workers=parse_positive_int(self.workers_var.get(), "下载线程"),
            request_delay=parse_float(self.delay_var.get(), "请求错峰秒"),
            scroll_pause=parse_float(self.pause_var.get(), "滚动等待秒"),
            upgrade_original=bool(self.upgrade_var.get()),
            pinimg_only=bool(self.pinimg_only_var.get()),
            download_images=bool(self.download_var.get()),
        )

    def _animate_title(self) -> None:
        color = self.title_colors[self.title_color_index % len(self.title_colors)]
        self.title_color_index += 1
        try:
            self.title_label.configure(fg=color)
            self.logo_canvas.itemconfigure("logo_r", fill=color)
        except Exception:
            pass
        self.root.after(700, self._animate_title)

    def _log(self, message: str) -> None:
        self.log_queue.put(message)

    def _drain_logs(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            if message == "__DONE__":
                self.start_button.configure(state="normal")
                self.stop_button.configure(state="disabled")
                continue
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
        self.root.after(100, self._drain_logs)


def parse_positive_int(value: str, label: str) -> int:
    try:
        number = int(str(value).strip())
    except ValueError as exc:
        raise ValueError("{} 必须是整数".format(label)) from exc
    if number < 0:
        raise ValueError("{} 不能小于 0".format(label))
    return number


def parse_float(value: str, label: str) -> float:
    try:
        number = float(str(value).strip())
    except ValueError as exc:
        raise ValueError("{} 必须是数字".format(label)) from exc
    if number < 0:
        raise ValueError("{} 不能小于 0".format(label))
    return number


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="RanGwaz browser-based image dataset collector")
    parser.add_argument("--gui", action="store_true", help="open the Tkinter window")
    parser.add_argument("--url", action="append", default=[], help="live start URL; can be passed more than once")
    parser.add_argument("--url-file", help="text file containing live URLs")
    parser.add_argument("--keyword", action="append", default=[], help="Pinterest search keyword; can be passed more than once")
    parser.add_argument("--keyword-file", help="text file containing Pinterest search keywords")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_DIR), help="output directory")
    parser.add_argument("--max-images", type=int, default=DEFAULT_TARGET_IMAGES)
    parser.add_argument("--max-scrolls", type=int, default=DEFAULT_START_SCROLLS)
    parser.add_argument("--detail-pages", type=int, default=DEFAULT_DETAIL_PAGES)
    parser.add_argument("--detail-scrolls", type=int, default=DEFAULT_DETAIL_SCROLLS)
    parser.add_argument("--detail-target-images", type=int, default=DEFAULT_DETAIL_TARGET_IMAGES)
    parser.add_argument("--login-wait-seconds", type=int, default=DEFAULT_LOGIN_WAIT_SECONDS)
    parser.add_argument("--login-email", default=os.environ.get("RANGWAZ_LOGIN_EMAIL", DEFAULT_LOGIN_EMAIL))
    parser.add_argument("--login-password", default=os.environ.get("RANGWAZ_LOGIN_PASSWORD", DEFAULT_LOGIN_PASSWORD))
    parser.add_argument("--workers", type=int, default=DEFAULT_DOWNLOAD_WORKERS)
    parser.add_argument("--scroll-pause", type=float, default=DEFAULT_SCROLL_PAUSE)
    parser.add_argument("--request-delay", type=float, default=DEFAULT_REQUEST_DELAY)
    parser.add_argument("--max-download-bytes", type=int, default=DEFAULT_MAX_DOWNLOAD_BYTES)
    parser.add_argument("--max-image-pixels", type=int, default=DEFAULT_MAX_IMAGE_PIXELS)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--no-upgrade-original", action="store_true")
    parser.add_argument("--allow-any-image-domain", action="store_true")
    parser.add_argument("--browser-profile", default=str(DEFAULT_BROWSER_PROFILE))
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run Chromium without a visible window; CAPTCHA or 2FA cannot be handled interactively",
    )
    parser.add_argument(
        "--fail-on-login-gate",
        action="store_true",
        help="stop instead of continuing when login, CAPTCHA, 2FA, or risk control is detected",
    )
    return parser


def load_urls(args: argparse.Namespace) -> List[str]:
    urls = [normalize_start_url(url) for url in (args.url or [])]
    if args.url_file:
        path = Path(args.url_file)
        urls.extend(normalize_start_url(line) for line in path.read_text(encoding="utf-8").splitlines())
    urls.extend(pinterest_search_url(keyword) for keyword in (args.keyword or []))
    if args.keyword_file:
        path = Path(args.keyword_file)
        urls.extend(pinterest_search_url(line) for line in path.read_text(encoding="utf-8").splitlines())
    return unique_list(urls)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.gui or len(sys.argv) == 1:
        DatasetCollectorApp().run()
        return 0

    urls = load_urls(args)
    if not urls:
        parser.error("at least one --url, --url-file, --keyword, or --keyword-file entry is required")

    config = CollectorConfig(
        output_dir=Path(args.output),
        start_urls=urls,
        max_images=max(0, args.max_images),
        max_scrolls=max(0, args.max_scrolls),
        detail_pages=max(0, args.detail_pages),
        detail_scrolls=max(0, args.detail_scrolls),
        detail_target_images=max(0, args.detail_target_images),
        login_wait_seconds=max(0, args.login_wait_seconds),
        login_email=args.login_email.strip(),
        login_password=args.login_password,
        workers=max(1, args.workers),
        request_delay=max(0.0, args.request_delay),
        scroll_pause=max(0.0, args.scroll_pause),
        upgrade_original=not args.no_upgrade_original,
        pinimg_only=not args.allow_any_image_domain,
        download_images=not args.no_download,
        browser_profile=Path(args.browser_profile),
        headless=args.headless,
        fail_on_login_gate=args.fail_on_login_gate or args.headless,
        max_download_bytes=max(1, args.max_download_bytes),
        max_image_pixels=max(1, args.max_image_pixels),
    )
    run_collection(config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
