"""
Internal canonical types — mirror Anthropic's Messages API shape.
"""
from dataclasses import dataclass
from typing import Any, Iterator


@dataclass
class AdapterResponse:
	content: list[dict]
	stop_reason: str
	usage: dict[str, Any]


class BaseAdapter:
	def chat(self, *, provider, model, messages, system, tools, max_tokens) -> AdapterResponse:
		raise NotImplementedError

	def stream_chat(self, *, provider, model, messages, system, tools, max_tokens) -> Iterator[dict]:
		raise NotImplementedError
