"""Avoid Frappe's \"Password not found\" dialogs when api_key was never set."""


def safe_provider_api_key(provider_doc) -> str:
	"""Return LLM Provider api_key or empty string; never raises or triggers password-not-found UI."""
	if not provider_doc:
		return ""
	try:
		from frappe.utils.password import get_decrypted_password

		key = get_decrypted_password(
			provider_doc.doctype,
			provider_doc.name,
			fieldname="api_key",
			raise_exception=False,
		)
		return (key or "").strip()
	except TypeError:
		# Older Frappe: fall back without raise_exception kw if signature differs
		try:
			return (provider_doc.get_password("api_key") or "").strip()
		except Exception:
			return ""
	except Exception:
		return ""
