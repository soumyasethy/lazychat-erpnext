"""Per-conversation schema cache. Each entry is a doctype's described
shape (fields, child tables, links, user corrections). Cached in
frappe.cache() (Redis) with a 30-minute TTL — long enough to span a
multi-step compose flow but short enough to recover from schema
migrations.

Used by `describe_doctype` (in tools.py): when called with an
explicit `conversation_id`, the result is interned here. Subsequent
calls within the same conversation return the cached result, saving
the LLM a redundant tool call.

API:
  schema_get(conversation_id, doctype) → cached dict | None
  schema_put(conversation_id, doctype, schema_dict) → None
  schema_clear(conversation_id, doctype=None) → None
    (with doctype=None, no-op until next TTL expiry — Frappe cache has
     no native pattern delete)
"""

import json

import frappe

_TTL = 1800
_PREFIX = "lazychat:schema_graph:"


def _key(conversation_id, doctype):
	return f"{_PREFIX}{conversation_id}::{doctype}"


def schema_get(conversation_id, doctype):
	"""Read-only lookup. Returns None on miss or parse failure."""
	if not conversation_id or not doctype:
		return None
	raw = frappe.cache().get_value(_key(conversation_id, doctype))
	if not raw:
		return None
	try:
		return json.loads(raw)
	except Exception:
		return None


def schema_put(conversation_id, doctype, schema_dict):
	"""Persist a doctype schema for a conversation. Caps at 30-min TTL."""
	if not conversation_id or not doctype:
		return
	frappe.cache().set_value(
		_key(conversation_id, doctype),
		json.dumps(schema_dict, default=str),
		expires_in_sec=_TTL,
	)


def schema_clear(conversation_id, doctype=None):
	"""Clear a single doctype's cache for a conversation. With
	doctype=None, this is a no-op until TTL expiry (Frappe cache has no
	native pattern delete; acceptable for v1)."""
	if doctype:
		frappe.cache().delete_value(_key(conversation_id, doctype))
		return
	# Wildcard delete deferred — TTL handles cleanup.
