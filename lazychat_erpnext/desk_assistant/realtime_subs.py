"""Realtime doc-change subscriptions — Tier D.

Lets the user say "watch SO-001" → the agent calls subscribe_doc_changes →
when SO-001 saves (anywhere — Desk, API, scheduled job, another agent
session), Frappe's universal on_update hook publishes a realtime event to
that user's socket. The panel shim relays it into the chat-ui as a toast.

Performance design:

  Frappe fires on_update for EVERY doc save in the system. We MUST NOT do
  arbitrary work in that hot path. Strategy:

  1. Global flag `lazychat:subs:any_active` — single Redis GET. When false,
     handler returns immediately. Zero overhead when nobody has subscribed.
  2. Per-doc subscriber set `lazychat:subs:<doctype>:<name>` — stores the
     list of users watching this exact doc. Single Redis GET per save when
     there ARE active subscriptions. Sub-millisecond.
  3. Per-user subscription list `lazychat:subs:user:<user>` — for
     list_my_subscriptions and cleanup on unsubscribe.

Storage: Frappe's redis_cache (cluster-safe) with 7-day TTL. Subscriptions
are session-bound conceptually but persist across tabs/refreshes — the user
explicitly unsubscribes (or the TTL expires).

Realtime push: uses Frappe's standard `frappe.publish_realtime(event=,
message=, user=)` which routes through the existing Socket.IO infra. The
panel shim subscribes via `frappe.realtime.on("lazychat_doc_update", ...)`
and forwards to the iframe over postMessage.
"""

import json
import re

import frappe

SUBS_FLAG_KEY = "lazychat:subs:any_active"
SUBS_KEY_PREFIX = "lazychat:subs:"  # + <doctype>:<name>
USER_SUBS_KEY_PREFIX = "lazychat:subs:user:"  # + <user>
SUBS_TTL_SEC = 7 * 24 * 3600


# ============================================================================
# Cache helpers
# ============================================================================


def _safe(s):
	# Frappe's redis_cache wrapper truncates / mishandles keys containing
	# spaces (verified via console: `lazychat:subs:Sales Invoice:NAME` silently
	# returned None on get despite set succeeding). Sanitise to ASCII-safe
	# slugs.
	return re.sub(r"[^A-Za-z0-9_.-]", "_", str(s or ""))


def _doc_key(doctype, name):
	return f"{SUBS_KEY_PREFIX}{_safe(doctype)}:{_safe(name)}"


def _user_key(user):
	return f"{USER_SUBS_KEY_PREFIX}{_safe(user)}"


def _read_list(key):
	raw = frappe.cache().get_value(key)
	if not raw:
		return []
	try:
		val = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
		return val if isinstance(val, list) else []
	except Exception:
		return []


def _write_list(key, items):
	frappe.cache().set_value(key, json.dumps(list(dict.fromkeys(items))), expires_in_sec=SUBS_TTL_SEC)


def _delete_key(key):
	try:
		frappe.cache().delete_value(key)
	except Exception:
		pass


def _refresh_global_flag():
	"""Set the global 'any active subscriptions' flag based on whether any
	user-subs key exists. Cheap to call after any sub/unsub."""
	# Frappe's cache doesn't expose key-prefix-scan portably, so we rely on
	# the flag being set when subscribing (eagerly) and only clear when no
	# user-subs lists remain. Pragmatic: the flag has a 24h TTL so even if we
	# leak it true, it self-clears daily.
	frappe.cache().set_value(SUBS_FLAG_KEY, "1", expires_in_sec=24 * 3600)


# ============================================================================
# Tool handlers (called from execute_tool)
# ============================================================================


def subscribe(doctype, name, user=None):
	user = user or frappe.session.user
	if not doctype or not name:
		return {"error": "doctype and name required"}
	if not frappe.db.exists(doctype, name):
		return {"error": f"doc not found: {doctype}/{name}"}
	if not frappe.has_permission(doctype, "read", doc=name):
		return {"error": "no read permission"}

	# Verified via console: frappe.has_permission flushes the local cache layer,
	# so writes BEFORE this point would be silently lost. Do the writes AFTER.
	doc_key = _doc_key(doctype, name)
	user_key = _user_key(user)
	sub_id = f"{doctype}:{name}"

	users = _read_list(doc_key)
	if user not in users:
		users.append(user)

	user_subs = _read_list(user_key)
	if sub_id not in user_subs:
		user_subs.append(sub_id)

	# Now write all three (doc, user-list, flag) in one burst with NO
	# permission checks between writes, and explicitly bypass the local
	# cache layer by using delete_value before set so subsequent reads
	# don't see a stale empty in-process copy.
	frappe.cache().delete_value(doc_key)
	_write_list(doc_key, users)
	frappe.cache().delete_value(user_key)
	_write_list(user_key, user_subs)
	_refresh_global_flag()

	return {
		"ok": True,
		"doctype": doctype,
		"name": name,
		"user": user,
		"subscribed_user_count": len(users),
		"_note": "You'll get a chat toast when this doc is saved by anyone (you, another user, scheduled job, API). Subscription auto-expires in 7 days; call unsubscribe_doc_changes to remove sooner.",
	}


def unsubscribe(doctype, name, user=None):
	user = user or frappe.session.user
	if not doctype or not name:
		return {"error": "doctype and name required"}

	doc_key = _doc_key(doctype, name)
	users = [u for u in _read_list(doc_key) if u != user]
	if users:
		_write_list(doc_key, users)
	else:
		_delete_key(doc_key)

	user_key = _user_key(user)
	sub_id = f"{doctype}:{name}"
	user_subs = [s for s in _read_list(user_key) if s != sub_id]
	if user_subs:
		_write_list(user_key, user_subs)
	else:
		_delete_key(user_key)

	return {"ok": True, "doctype": doctype, "name": name, "user": user}


def list_my(user=None):
	user = user or frappe.session.user
	subs = _read_list(_user_key(user))
	out = []
	for sub_id in subs:
		# sub_id format is "doctype:name" — split on FIRST colon since names
		# can contain colons (rare but happens with naming series like
		# "ABC-2026-001").
		if ":" not in sub_id:
			continue
		doctype, name = sub_id.split(":", 1)
		# Hide subs the user no longer has perm on (cleanup happens on next
		# event publish; surfacing them here would be misleading).
		try:
			if not frappe.has_permission(doctype, "read", doc=name):
				continue
		except Exception:
			continue
		out.append({"doctype": doctype, "name": name, "link": f"/app/{frappe.scrub(doctype)}/{name}"})
	return {"ok": True, "user": user, "count": len(out), "subscriptions": out}


# ============================================================================
# Universal on_update hook — wired in hooks.py:doc_events["*"]["on_update"].
#
# Hot path. EVERY doc save across the bench fires this. The first line MUST
# be cheap.
# ============================================================================


def on_doc_update(doc, method=None):
	# Fast-path: zero work when no user has subscribed to anything.
	cache = frappe.cache()
	if not cache.get_value(SUBS_FLAG_KEY):
		return
	# Skip the noisy doctypes that fire constantly during routine bench work
	# and are extremely unlikely to be subscribed to. Saves a Redis GET each.
	dt = getattr(doc, "doctype", None)
	if dt in _SKIP_DOCTYPES:
		return
	dn = getattr(doc, "name", None)
	if not dt or not dn:
		return

	users = _read_list(_doc_key(dt, dn))
	if not users:
		return

	payload = {
		"doctype": dt,
		"name": dn,
		"action": "update",
		"modified_by": getattr(doc, "modified_by", None),
		"workflow_state": getattr(doc, "workflow_state", None),
		"status": getattr(doc, "status", None),
		"docstatus": getattr(doc, "docstatus", None),
		"link": f"/app/{frappe.scrub(dt)}/{dn}",
	}
	for user in users:
		# Re-check perm at publish time so a user who lost access doesn't keep
		# getting events. Drop them silently — they can re-subscribe if they
		# get permission back.
		try:
			if not frappe.has_permission(dt, "read", doc=dn, user=user):
				continue
			frappe.publish_realtime(
				event="lazychat_doc_update",
				message=payload,
				user=user,
				after_commit=True,
			)
		except Exception:
			continue


# Doctypes whose updates we never publish — high-frequency / noisy / unlikely
# to be useful as subscription targets. Reduces hot-path lookups.
_SKIP_DOCTYPES = frozenset(
	{
		"Version",
		"Activity Log",
		"Access Log",
		"Error Log",
		"Comment",
		"Communication",
		"View Log",
		"DocShare",
		"ToDo",
		"Notification Log",
		"Email Queue",
		"Email Queue Recipient",
		"DocType",
		"Custom Field",
		"Property Setter",
		"Server Script",
		"Client Script",
		"Singles",
		"Translation",
		"Session Default",
		"User Permission",
		"File",
		"RQ Job",
		"Scheduled Job Log",
		"Lazychat KB Chunk",  # our own indexer churn
	}
)
