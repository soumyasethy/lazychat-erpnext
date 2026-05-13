"""Runtime patches for Frappe's Page doctype to support API-created Pages.

Frappe v15's `Page.load_assets()` unconditionally:
1. Resets `self.script = ""` at the top.
2. Calls `os.listdir(<module_path>/page/<scrub(name)>/)` to enumerate disk files.

Both behaviors break Pages created via the API (e.g. via Cycle 13's
`prepare_create_page`):
- The disk dir doesn't exist → `FileNotFoundError` → HTTP 500 from
  `frappe.desk.desk_page.getpage`.
- Even if we create the dir, `self.script` is reset to empty before the
  HTML-file iteration runs, wiping the DB-stored JS.

Fix: monkey-patch `Page.load_assets` to short-circuit for `standard != "Yes"`
rows. Standard pages (built into apps via on-disk `page/<name>/<name>.js`
files) still use the original loader. Non-standard pages (anything stored
in the DB content/style/script fields) skip disk loading entirely — DB
values are preserved.

Installed once per worker via the `before_request` hook in `hooks.py`.
Idempotent: re-applying just re-binds to the same wrapper.
"""

from __future__ import annotations

import frappe

_PATCHED_FLAG = "_lazychat_load_assets_patched"


def install_page_load_assets_patch():
	"""Install the load_assets patch once per Python process.

	Cheap: a single attribute check + reference assignment when already
	patched. The before_request hook calls this on every request; the flag
	gate keeps the per-request cost at ~one isinstance check.
	"""
	try:
		from frappe.core.doctype.page.page import Page
	except Exception:
		return  # Frappe not fully initialized; will retry next request

	if getattr(Page, _PATCHED_FLAG, False):
		return

	_original = Page.load_assets

	def load_assets_patched(self):
		# Standard pages (shipped as on-disk files inside a Frappe app) still
		# need the original loader. Anything else (API-created via prepare_*,
		# or hand-edited in /app/page/new) keeps its DB-stored fields.
		if (self.get("standard") or "").strip() == "Yes":
			return _original(self)
		# DB-only: nothing to do. content / style / script are already populated
		# by `frappe.get_doc("Page", name)` before this method runs.
		return None

	load_assets_patched.__wrapped__ = _original  # type: ignore[attr-defined]
	Page.load_assets = load_assets_patched
	setattr(Page, _PATCHED_FLAG, True)


def before_request_hook():
	"""before_request hook entry — wraps the patch installer in defensive
	try/except so a patch failure never blocks the request."""
	try:
		install_page_load_assets_patch()
	except Exception as e:
		try:
			frappe.logger().warning(f"[lazychat] page_patches.install failed: {e}")
		except Exception:
			pass
