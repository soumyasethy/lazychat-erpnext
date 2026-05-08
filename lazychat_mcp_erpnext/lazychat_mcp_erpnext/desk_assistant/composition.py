"""Composition session — Redis-backed transient state for the M2 iterative
test-driven loop. Each session represents one user-intent compose flow;
multiple iterations of (compose → probe → analyze) accumulate against
the same intent_hash key.

Lifecycle:
  open_or_resume_session(intent_summary, action) → session dict
  append_iteration(intent_hash, iter_payload) → updated session dict
  finalize_session(intent_hash, outcome) → mark closed, leave for TTL cleanup

TTL: 90s. Long enough to span 5 iterations + critic + user latency.
"""

import hashlib
import json
import time

import frappe

_TTL_SEC = 90
_KEY_PREFIX = "lazychat:composition:"
_MAX_ITERATIONS = 5  # hard ceiling (Effort gates the soft cap below this)


def _intent_hash(intent_summary, action):
	h = hashlib.sha1(
		f"{action}::{(intent_summary or '').strip()}::{frappe.session.user}".encode()
	).hexdigest()[:16]
	return h


def _key(intent_hash):
	return f"{_KEY_PREFIX}{intent_hash}"


def open_or_resume_session(intent_summary, action):
	"""Open a new session OR resume an existing one keyed by intent_hash.
	Resume is idempotent — same input returns the same hash + state.
	"""
	if not intent_summary or not action:
		raise ValueError("intent_summary and action required")
	h = _intent_hash(intent_summary, action)
	cache = frappe.cache()
	raw = cache.get_value(_key(h))
	if raw:
		try:
			return json.loads(raw)
		except Exception:
			pass
	sess = {
		"intent_hash": h,
		"intent_summary": intent_summary[:800],
		"action": action,
		"user": frappe.session.user,
		"iterations": [],
		"iteration_count": 0,
		"status": "open",
		"started_at": time.time(),
	}
	cache.set_value(_key(h), json.dumps(sess), expires_in_sec=_TTL_SEC)
	return sess


def append_iteration(intent_hash, iter_payload):
	"""Append one iteration record. iter_payload is a dict with at least
	{payload, probe_result, analyze_verdict}. Caps at _MAX_ITERATIONS
	(hard) — Effort-level soft cap is enforced by the caller."""
	cache = frappe.cache()
	raw = cache.get_value(_key(intent_hash))
	if not raw:
		raise ValueError(f"composition session {intent_hash} not found / expired")
	sess = json.loads(raw)
	if sess.get("status") != "open":
		raise ValueError(f"session {intent_hash} status={sess.get('status')!r}, cannot append")
	if sess["iteration_count"] >= _MAX_ITERATIONS:
		raise ValueError(f"hard cap of {_MAX_ITERATIONS} iterations reached for {intent_hash}")
	sess["iterations"].append({"n": sess["iteration_count"] + 1, **iter_payload})
	sess["iteration_count"] += 1
	cache.set_value(_key(intent_hash), json.dumps(sess), expires_in_sec=_TTL_SEC)
	return sess


def finalize_session(intent_hash, outcome):
	"""Mark session closed (outcome ∈ {ok, mismatch_capped, error})."""
	cache = frappe.cache()
	raw = cache.get_value(_key(intent_hash))
	if not raw:
		return None
	sess = json.loads(raw)
	sess["status"] = "closed"
	sess["outcome"] = outcome
	sess["closed_at"] = time.time()
	cache.set_value(_key(intent_hash), json.dumps(sess), expires_in_sec=_TTL_SEC)
	return sess


def get_session(intent_hash):
	"""Read-only session lookup. Returns None on miss."""
	raw = frappe.cache().get_value(_key(intent_hash))
	return json.loads(raw) if raw else None
