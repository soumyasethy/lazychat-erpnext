"""Avoid Frappe's \"Password not found\" dialogs when api_key was never set.

Also handles thread-pool worker reads: Frappe's password decryption needs
`frappe.local` context (DB cursor, encryption_key from site_config) which
isn't propagated to ThreadPoolExecutor workers. We cache the decrypted key
on the provider_doc as a non-persisted attribute (`__lazychat_plain_key__`)
so subsequent reads inside worker threads (e.g. visual_judge.compare's vision
call) can use it without re-entering Frappe's password machinery.
"""

_CACHE_ATTR = "__lazychat_plain_api_key__"


def safe_provider_api_key(provider_doc) -> str:
	"""Return LLM Provider api_key or empty string; never raises or triggers password-not-found UI.

	Caches the plaintext on `provider_doc` so subsequent calls (including from
	threadpool workers without Frappe context) get the same value cheaply.
	"""
	if not provider_doc:
		return ""
	# Cache hit — works in worker threads where Frappe context isn't available
	cached = getattr(provider_doc, _CACHE_ATTR, None)
	if cached:
		return cached
	try:
		from frappe.utils.password import get_decrypted_password

		key = get_decrypted_password(
			provider_doc.doctype,
			provider_doc.name,
			fieldname="api_key",
			raise_exception=False,
		)
		key = (key or "").strip()
	except TypeError:
		# Older Frappe: fall back without raise_exception kw if signature differs
		try:
			key = (provider_doc.get_password("api_key") or "").strip()
		except Exception:
			key = ""
	except Exception:
		key = ""
	if key:
		try:
			setattr(provider_doc, _CACHE_ATTR, key)
		except Exception:
			pass  # frozen object — fine, just no caching
	return key


def warm_provider_api_key(provider_doc) -> str:
	"""Eagerly resolve + cache the api_key in the current (Frappe-rich) context.

	Call this in the main thread before handing `provider_doc` off to a
	ThreadPoolExecutor worker that will call `safe_provider_api_key()` later
	(workers don't have Frappe context for password decryption).

	Returns the resolved key (so callers can short-circuit if missing).
	"""
	return safe_provider_api_key(provider_doc)
