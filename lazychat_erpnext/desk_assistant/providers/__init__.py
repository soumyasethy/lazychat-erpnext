import frappe
from frappe import _

from lazychat_erpnext.desk_assistant.providers.anthropic import AnthropicAdapter
from lazychat_erpnext.desk_assistant.providers.openai_compat import OpenAICompatAdapter

_REGISTRY = {
	"anthropic": AnthropicAdapter(),
	"openai_compatible": OpenAICompatAdapter(),
}


def get_adapter(provider_type):
	if provider_type not in _REGISTRY:
		frappe.throw(f"No adapter for provider_type={provider_type}")
	return _REGISTRY[provider_type]


def resolve_model(model_label=None):
	filters = {"enabled": 1}
	if model_label:
		filters["model_label"] = model_label
	else:
		filters["is_default"] = 1
	names = frappe.get_all("LLM Model", filters=filters, pluck="name", limit=1)
	if not names and model_label:
		frappe.throw(_("Unknown or disabled model: {0}").format(model_label))
	if not names and not model_label:
		names = frappe.get_all(
			"LLM Model",
			filters={"enabled": 1},
			pluck="name",
			limit=1,
			order_by="modified desc",
		)
	if not names:
		frappe.throw(
			_("No enabled LLM Model found. Open LLM Model and set a default, or pick a model."),
			title=_("Lazychat MCP ERPNext"),
		)
	model = frappe.get_doc("LLM Model", names[0])
	provider = frappe.get_doc("LLM Provider", model.provider)
	if not provider.enabled:
		frappe.throw(_("Provider {0} is disabled").format(provider.provider_name))
	return model, provider, get_adapter(provider.provider_type)
