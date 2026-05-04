import requests

from lazychat_mcp_erpnext.desk_assistant.password_utils import safe_provider_api_key
from lazychat_mcp_erpnext.desk_assistant.providers.base import AdapterResponse, BaseAdapter


class AnthropicAdapter(BaseAdapter):
	def chat(self, *, provider, model, messages, system, tools, max_tokens):
		headers = {
			"x-api-key": safe_provider_api_key(provider),
			"anthropic-version": "2023-06-01",
			"content-type": "application/json",
		}
		if provider.extra_headers:
			import json as _json

			headers.update(_json.loads(provider.extra_headers))

		body = {
			"model": model.model_id,
			"max_tokens": max_tokens or model.max_output_tokens or 4096,
			"system": system,
			"messages": messages,
		}
		if tools and model.supports_tools:
			body["tools"] = tools

		r = requests.post(f"{provider.base_url}/messages", headers=headers, json=body, timeout=120)
		r.raise_for_status()
		data = r.json()
		return AdapterResponse(
			content=data["content"],
			stop_reason=data.get("stop_reason", "end_turn"),
			usage=data.get("usage", {}),
		)
