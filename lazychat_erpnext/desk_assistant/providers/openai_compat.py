import json

import requests

from lazychat_erpnext.desk_assistant.password_utils import safe_provider_api_key
from lazychat_erpnext.desk_assistant.providers.base import AdapterResponse, BaseAdapter


class OpenAICompatAdapter(BaseAdapter):
	def chat(self, *, provider, model, messages, system, tools, max_tokens):
		oai_messages = self._to_oai_messages(system, messages)
		oai_tools = self._to_oai_tools(tools) if tools and model.supports_tools else None

		headers = {
			"Authorization": f"Bearer {safe_provider_api_key(provider)}",
			"Content-Type": "application/json",
		}
		if provider.extra_headers:
			headers.update(json.loads(provider.extra_headers))

		body = {
			"model": model.model_id,
			"messages": oai_messages,
			"max_tokens": max_tokens or model.max_output_tokens or 4096,
		}
		if oai_tools:
			body["tools"] = oai_tools
			body["tool_choice"] = "auto"

		r = requests.post(
			f"{provider.base_url.rstrip('/')}/chat/completions",
			headers=headers,
			json=body,
			timeout=120,
		)
		r.raise_for_status()
		data = r.json()
		choice = data["choices"][0]
		msg = choice["message"]
		finish = choice.get("finish_reason", "stop")

		content_blocks = self._from_oai_message(msg)
		stop_reason = (
			"tool_use"
			if finish == "tool_calls"
			else ("max_tokens" if finish == "length" else "end_turn")
		)
		usage = data.get("usage", {})
		return AdapterResponse(
			content=content_blocks,
			stop_reason=stop_reason,
			usage={
				"input_tokens": usage.get("prompt_tokens", 0),
				"output_tokens": usage.get("completion_tokens", 0),
			},
		)

	@staticmethod
	def _to_oai_messages(system, messages):
		out = []
		if system:
			out.append({"role": "system", "content": system})
		for m in messages:
			role = m["role"]
			content = m["content"]

			if role == "user" and isinstance(content, list):
				tool_results = [b for b in content if b.get("type") == "tool_result"]
				other = [b for b in content if b.get("type") != "tool_result"]
				for tr in tool_results:
					out.append(
						{
							"role": "tool",
							"tool_call_id": tr["tool_use_id"],
							"content": tr["content"]
							if isinstance(tr["content"], str)
							else json.dumps(tr["content"]),
						}
					)
				if not other:
					continue
				has_image = any(b.get("type") == "image" for b in other)
				if has_image:
					oai_parts = []
					for b in other:
						if b.get("type") == "text":
							oai_parts.append({"type": "text", "text": b.get("text", "")})
						elif b.get("type") == "image":
							src = b.get("source") or {}
							if src.get("type") == "base64":
								mime = src.get("media_type") or "image/png"
								data = src.get("data") or ""
								oai_parts.append(
									{
										"type": "image_url",
										"image_url": {"url": f"data:{mime};base64,{data}"},
									}
								)
					if oai_parts:
						out.append({"role": "user", "content": oai_parts})
					continue
				text_parts = [b.get("text", "") for b in other if b.get("type") == "text"]
				if text_parts:
					out.append({"role": "user", "content": "\n".join(text_parts)})
				continue

			if role == "user":
				out.append({"role": "user", "content": content})
				continue

			if role == "assistant" and isinstance(content, list):
				text_parts, tool_calls = [], []
				for b in content:
					if b.get("type") == "text":
						text_parts.append(b["text"])
					elif b.get("type") == "tool_use":
						tool_calls.append(
							{
								"id": b["id"],
								"type": "function",
								"function": {
									"name": b["name"],
									"arguments": json.dumps(b["input"] or {}),
								},
							}
						)
				oai_msg = {"role": "assistant"}
				oai_msg["content"] = "\n".join(text_parts) if text_parts else ""
				if tool_calls:
					oai_msg["tool_calls"] = tool_calls
				out.append(oai_msg)
				continue

			out.append({"role": role, "content": content})
		return out

	@staticmethod
	def _to_oai_tools(tools):
		return [
			{
				"type": "function",
				"function": {
					"name": t["name"],
					"description": t.get("description", ""),
					"parameters": t["input_schema"],
				},
			}
			for t in tools
		]

	@staticmethod
	def _from_oai_message(msg):
		blocks = []
		text = msg.get("content")
		if text:
			blocks.append({"type": "text", "text": text})
		for tc in msg.get("tool_calls") or []:
			try:
				args = json.loads(tc["function"]["arguments"] or "{}")
			except json.JSONDecodeError:
				args = {"_raw": tc["function"]["arguments"]}
			blocks.append(
				{
					"type": "tool_use",
					"id": tc["id"],
					"name": tc["function"]["name"],
					"input": args,
				}
			)
		return blocks
