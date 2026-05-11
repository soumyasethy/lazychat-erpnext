"""Lazychat Skills — runtime activation, prompt composition, tool filtering.

A Skill is a Lazychat Skill doctype row carrying a system_prompt snippet and
an optional allowed_tools JSON array. Users activate skills from the chat-ui
`/` palette; the active set is stored per-user in Redis under
`lazychat:skills:active:<user>` with a 7-day TTL (refreshed on each touch).

When the agent runs:
  1. claude_bridge._system_prompt() / routerSystemPrompt.buildSystemPrompt()
     calls compose_active_prompt(base) to append active skill snippets.
  2. mcp.dispatch() / claude_bridge tool registry consults
     filter_tools_for_user() to optionally restrict the LLM's view of tools.

The chat-ui never trusts the active set directly — it always re-reads via
list_skills() so server-side state is the source of truth.
"""

import json

import frappe

ACTIVE_KEY_PREFIX = "lazychat:skills:active:"
ACTIVE_TTL_SEC = 7 * 24 * 3600  # 7 days; refreshed on every touch


def _active_key(user=None):
	user = user or frappe.session.user
	return ACTIVE_KEY_PREFIX + user


def get_active_skill_names(user=None):
	"""Return the list of currently-active skill names for the user.

	Empty list means no skills active = base prompt + all tools (default).
	Non-existent / disabled / inaccessible skills are filtered out so a stale
	Redis entry can never resurrect a deleted skill.
	"""
	raw = frappe.cache().get_value(_active_key(user))
	if not raw:
		return []
	try:
		names = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
	except Exception:
		return []
	if not isinstance(names, list):
		return []
	visible = _visible_skill_names(user=user)
	return [n for n in names if isinstance(n, str) and n in visible]


def _set_active_skill_names(names, user=None):
	user = user or frappe.session.user
	value = json.dumps(list(dict.fromkeys(names)))  # de-dupe, preserve order
	frappe.cache().set_value(_active_key(user), value, expires_in_sec=ACTIVE_TTL_SEC)


def _visible_skill_names(user=None):
	"""Set of skill names the user is allowed to see (own + public, enabled only)."""
	user = user or frappe.session.user
	rows = frappe.get_all(
		"Lazychat Skill",
		filters={"enabled": 1},
		or_filters=[{"is_public": 1}, {"owner": user}],
		fields=["name"],
	)
	return {r["name"] for r in rows}


def list_skills_for_user(user=None):
	"""Return enabled skills the user can see (own + public), with active flag.

	Each row: {name, title, description, is_public, owner_user, allowed_tools (parsed list or None), active}.
	Used by the chat-ui Skills palette.
	"""
	user = user or frappe.session.user
	rows = frappe.get_all(
		"Lazychat Skill",
		filters={"enabled": 1},
		or_filters=[{"is_public": 1}, {"owner": user}],
		fields=["name", "title", "description", "is_public", "owner", "allowed_tools"],
		order_by="is_public desc, title asc",
	)
	active = set(get_active_skill_names(user=user))
	out = []
	for r in rows:
		tools = None
		raw = (r.get("allowed_tools") or "").strip()
		if raw:
			try:
				parsed = json.loads(raw)
				if isinstance(parsed, list):
					tools = [t for t in parsed if isinstance(t, str)]
			except Exception:
				tools = None
		out.append(
			{
				"name": r["name"],
				"title": r.get("title") or r["name"],
				"description": r.get("description") or "",
				"is_public": bool(r.get("is_public")),
				"owner_user": r.get("owner"),
				"allowed_tools": tools,
				"active": r["name"] in active,
			}
		)
	return out


def activate_skill(skill_name, user=None):
	"""Add a skill to the user's active set. No-op if already active."""
	user = user or frappe.session.user
	visible = _visible_skill_names(user=user)
	if skill_name not in visible:
		return {"error": f"skill '{skill_name}' not found or you don't have access"}
	current = get_active_skill_names(user=user)
	if skill_name not in current:
		current.append(skill_name)
	_set_active_skill_names(current, user=user)
	return {"ok": True, "active": current}


def deactivate_skill(skill_name, user=None):
	"""Remove a skill from the user's active set."""
	user = user or frappe.session.user
	current = [n for n in get_active_skill_names(user=user) if n != skill_name]
	_set_active_skill_names(current, user=user)
	return {"ok": True, "active": current}


def compose_active_prompt(base_prompt, user=None):
	"""Append active skill prompts onto the base system prompt.

	Output format (separators help the model see the boundary):

	    <base_prompt>

	    --- Active skill: AR Collections ---
	    <skill 1 system_prompt>

	    --- Active skill: Item Onboarding ---
	    <skill 2 system_prompt>
	"""
	user = user or frappe.session.user
	names = get_active_skill_names(user=user)
	if not names:
		return base_prompt
	parts = [base_prompt.rstrip()]
	for name in names:
		try:
			doc = frappe.get_doc("Lazychat Skill", name)
		except Exception:
			continue
		if not doc.enabled:
			continue
		title = doc.title or name
		snippet = (doc.system_prompt or "").strip()
		if snippet:
			parts.append(f"\n\n--- Active skill: {title} ---\n{snippet}")
	return "".join(parts)


def filter_tools_for_user(all_tool_schemas, user=None):
	"""Filter a list of tool schemas to the union of `allowed_tools` across active
	skills. Returns the input unchanged when no skill restricts tools.

	`all_tool_schemas` is a list of dicts each with a "name" key (matches the
	shape of TOOL_SCHEMAS and the MCP tools/list response).
	"""
	user = user or frappe.session.user
	names = get_active_skill_names(user=user)
	if not names:
		return all_tool_schemas
	allowed_union = None  # None = unrestricted; set = whitelist
	for name in names:
		try:
			doc = frappe.get_doc("Lazychat Skill", name)
		except Exception:
			continue
		raw = (doc.allowed_tools or "").strip()
		if not raw:
			continue
		try:
			parsed = json.loads(raw)
		except Exception:
			continue
		if not isinstance(parsed, list):
			continue
		tool_set = {t for t in parsed if isinstance(t, str)}
		if allowed_union is None:
			allowed_union = tool_set
		else:
			allowed_union = allowed_union | tool_set
	if allowed_union is None:
		return all_tool_schemas
	return [t for t in all_tool_schemas if t.get("name") in allowed_union]
