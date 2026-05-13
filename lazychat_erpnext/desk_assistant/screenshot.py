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
	global _browser
	if _browser is not None:
		return _browser
	with _browser_lock:
		if _browser is not None:
			return _browser
		from playwright.sync_api import sync_playwright
		_pw = sync_playwright().start()
		_browser = _pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
		return _browser


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
def capture(route, viewport=None, wait_for_dataset="lazychatReady", timeout_ms=5000):
	"""See module docstring."""
	user = frappe.session.user if frappe.session else None
	if not user or user == "Guest":
		return {"ok": False, "error": "screenshot.capture: Guest user not permitted; sign in first."}

	settings_enabled = frappe.db.get_single_value("Lazychat Settings", "enable_screenshot_preview")
	if settings_enabled is not None and not int(settings_enabled or 0):
		return {"ok": False, "error": "screenshot preview is disabled in Lazychat Settings."}

	if not is_available():
		return {"ok": False, "error": "playwright not installed — run `./env/bin/pip install playwright && ./env/bin/playwright install chromium` on the bench."}

	if not isinstance(route, str) or not route.startswith("/"):
		return {"ok": False, "error": f"route must start with '/' (got: {route!r})"}
	if not (route.startswith("/app/") or route.startswith("/files/") or route.startswith("/private/files/")):
		return {"ok": False, "error": f"route '{route}' is not a Desk path. Only /app/* / /files/* / /private/files/* are screenshotable."}

	err = _ensure_capacity()
	if err:
		return err

	width = int((viewport or {}).get("width") or 1440)
	height = int((viewport or {}).get("height") or 900)
	timeout_ms = min(max(int(timeout_ms or 5000), 500), 20000)

	# Bench-side capture talks to the local gunicorn directly via 127.0.0.1.
	# Using frappe.utils.get_url() can produce hostnames like `erp.local` that
	# headless Chromium can't resolve (ERR_NAME_NOT_RESOLVED). 127.0.0.1 is
	# always reachable from the same machine and works for both dev (bench serve)
	# and prod (gunicorn listens on 127.0.0.1 behind nginx).
	port = int(frappe.conf.get("webserver_port") or 8000)
	base_url = f"http://127.0.0.1:{port}"
	try:
		with _capture_lock:
			browser = _get_browser()
			context = browser.new_context(viewport={"width": width, "height": height})
			try:
				sid = getattr(frappe.local.session, "sid", None) if frappe.local.session else None
				if sid:
					context.add_cookies([{
						"name": "sid", "value": sid, "domain": "127.0.0.1",
						"path": "/", "sameSite": "Lax",
					}])
				page = context.new_page()
				full_url = base_url + route
				page.goto(full_url, wait_until="networkidle", timeout=timeout_ms + 2000)
				ready_seen = False
				try:
					page.wait_for_function(
						f"() => document.body && document.body.dataset && document.body.dataset[{wait_for_dataset!r}] === '1'",
						timeout=timeout_ms,
					)
					ready_seen = True
				except Exception:
					pass
				png_bytes = page.screenshot(full_page=False, type="png")
				page.close()
			finally:
				context.close()

		b64 = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
		import time
		return {
			"ok": True,
			"screenshot_b64": b64,
			"width": width,
			"height": height,
			"capture_method": "playwright",
			"ready_signal_seen": ready_seen,
			"captured_at": int(time.time() * 1000),
		}
	except Exception as e:
		return {"ok": False, "error": f"capture failed: {type(e).__name__}: {e}"}
	finally:
		_release_capacity()


def is_available() -> bool:
	"""Return True if Playwright is importable.

	Chromium presence is verified at capture time (browser launch). We do NOT
	probe with `sync_playwright()` here because that starts a new playwright
	instance, which cannot coexist with the persistent browser pool from
	`_get_browser()` — the second call would fail or hang after the first
	capture has launched the long-lived browser. Keep this check cheap +
	idempotent: just the import.
	"""
	try:
		import playwright.sync_api  # noqa: F401
		return True
	except ImportError:
		return False
