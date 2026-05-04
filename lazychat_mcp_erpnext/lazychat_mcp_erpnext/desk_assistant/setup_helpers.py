"""One-shot helpers for configuring LLM Provider + LLM Model from the bench CLI.

Usage:
    bench --site <site> execute lazychat_mcp_erpnext.desk_assistant.setup_helpers.configure_provider_model \\
        --kwargs '{"provider_name": "NVIDIA", "model_id": "bytedance/seed-oss-36b-instruct", "model_label": "NVIDIA Bytedance Seed", "supports_tools": 0, "make_default": 1}'

API keys are NOT taken via this script (would land in shell history). Set via Desk UI:
    /app/llm-provider/<provider_name>  → paste API Key → Save.
"""
import frappe


def configure_provider_model(
	provider_name: str,
	model_id: str,
	model_label: str | None = None,
	supports_tools: int = 0,
	max_output_tokens: int = 4096,
	context_window: int = 32000,
	make_default: int = 1,
):
	"""Enable a Provider and create/upsert an LLM Model row pointing at it.

	Returns a summary dict; also prints a banner with next steps.
	Does NOT set the API key — user does that in Desk for security.
	"""
	if not frappe.db.exists("LLM Provider", provider_name):
		return {"ok": False, "error": f"LLM Provider '{provider_name}' not found"}

	# 1. Enable the provider
	p = frappe.get_doc("LLM Provider", provider_name)
	if not p.enabled:
		p.enabled = 1
		p.save(ignore_permissions=True)

	# 2. Upsert the LLM Model
	label = model_label or f"{provider_name} {model_id}"
	existing = frappe.db.exists("LLM Model", {"model_label": label})
	if existing:
		m = frappe.get_doc("LLM Model", existing)
		m.model_id = model_id
		m.provider = provider_name
		m.supports_tools = int(supports_tools)
		m.max_output_tokens = int(max_output_tokens)
		m.context_window = int(context_window)
		m.enabled = 1
		if make_default:
			m.is_default = 1
		m.save(ignore_permissions=True)
	else:
		m = frappe.get_doc(
			{
				"doctype": "LLM Model",
				"model_label": label,
				"provider": provider_name,
				"model_id": model_id,
				"supports_tools": int(supports_tools),
				"max_output_tokens": int(max_output_tokens),
				"context_window": int(context_window),
				"is_default": int(make_default),
				"enabled": 1,
			}
		)
		m.insert(ignore_permissions=True)

	# 3. Demote other defaults (only one row should have is_default=1 at a time)
	if make_default:
		others = frappe.get_all(
			"LLM Model",
			filters={"is_default": 1, "model_label": ["!=", label]},
			fields=["name"],
		)
		for o in others:
			d = frappe.get_doc("LLM Model", o.name)
			d.is_default = 0
			d.save(ignore_permissions=True)

	frappe.db.commit()

	# Check whether the API key is set
	from lazychat_mcp_erpnext.desk_assistant.password_utils import safe_provider_api_key

	key = safe_provider_api_key(p)
	site = getattr(frappe.local, "site", "<site>")
	banner = (
		"\n"
		"================================================================\n"
		f" Provider:  {provider_name}  (enabled={p.enabled})\n"
		f" API key:   {'SET' if key else 'NOT SET — paste it in Desk UI to enable chat'}\n"
		f" Model:     {label}\n"
		f"   id:      {model_id}\n"
		f"   tools:   {bool(supports_tools)}\n"
		f"   default: {bool(make_default)}\n"
	)
	if not key:
		banner += (
			" Next:\n"
			f"   1. Open http://localhost:8000/app/llm-provider/{provider_name.replace(' ', '%20')}\n"
			"   2. Paste your API Key in the 'API Key' field, Save.\n"
			"   3. Hard-refresh /app, open the chat panel.\n"
			"   4. In chat-ui's model picker, switch to 'Default' (or the new label above).\n"
		)
	else:
		banner += (
			" Next:\n"
			"   1. Hard-refresh /app, open the chat panel.\n"
			"   2. In chat-ui's model picker, switch to 'Default' (or the new label above).\n"
			"   3. Try 'top 5 customers by total purchases' — should call get_sales_summary.\n"
		)
	banner += "================================================================\n"
	print(banner)
	return {
		"ok": True,
		"provider": provider_name,
		"provider_enabled": bool(p.enabled),
		"api_key_set": bool(key),
		"model_label": label,
		"model_id": model_id,
		"made_default": bool(make_default),
	}
