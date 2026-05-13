"""Bench-side Playwright service for the M2 screenshot preview.

`capture(route, viewport, wait_for_dataset, timeout_ms)` renders an internal
Desk route in headless Chromium AS THE CALLING USER (cookie-injected from
frappe.session) and returns base64 PNG. Used by chat-ui's screenshot Message
kind after a create_page / update_doc(Page) Apply success.

Auth model: requires authenticated session. Refuses for Guest. The Playwright
context injects the calling user's session cookie so the rendered page sees
the same permissions as the caller would in their browser.

Concurrency: single-slot serializer with a small queue. Browser pool of N
persistent Chromium pages (reused across requests). Per-request: new tab,
inject cookie, navigate, wait for ready signal OR timeout, screenshot.

Gated by Lazychat Settings.enable_screenshot_preview. If Playwright is not
installed, returns {ok: False, error: "playwright not installed — ..."}.
"""
from __future__ import annotations
import base64
import threading
from typing import Optional

import frappe


_capture_lock = threading.Lock()
_max_queue_depth = 4
_queue_count = 0
_queue_count_lock = threading.Lock()

_browser = None
_browser_lock = threading.Lock()


def _get_browser():
	"""Create or return the persistent Chromium browser. Lazy-imports Playwright."""
	raise NotImplementedError  # filled in M2.2


def _ensure_capacity() -> Optional[dict]:
	global _queue_count
	with _queue_count_lock:
		if _queue_count >= _max_queue_depth:
			return {"ok": False, "error": f"screenshot service at capacity ({_queue_count}/{_max_queue_depth} pending). Retry in a moment."}
		_queue_count += 1
	return None


def _release_capacity():
	global _queue_count
	with _queue_count_lock:
		_queue_count = max(0, _queue_count - 1)


@frappe.whitelist()
def capture(route: str, viewport: Optional[dict] = None, wait_for_dataset: str = "lazychatReady", timeout_ms: int = 5000) -> dict:
	raise NotImplementedError  # filled in M2.2


def is_available() -> bool:
	try:
		import playwright.sync_api  # noqa: F401
	except ImportError:
		return False
	try:
		from playwright.sync_api import sync_playwright
		with sync_playwright() as p:
			_ = p.chromium.executable_path
		return True
	except Exception:
		return False
