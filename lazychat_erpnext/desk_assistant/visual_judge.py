"""LLM-as-judge for visual comparison of reference-vs-candidate dashboards.

Reuses critic.py pattern (Cycle 9 M2). Two methods:
- compare(): vision LLM call.
- generate_fixes(): text-only LLM call.

Effort gating:
- low/medium: skip immediately.
- high: 1 iter cap; default model 'claude-sonnet-4-6'.
- max: 3 iter cap; default model 'claude-opus-4-7'.
"""
from __future__ import annotations
import concurrent.futures
import json
import re
from typing import Optional

import frappe


_EFFORT_DEFAULT_MODELS = {
	"high": "claude-sonnet-4-6",
	"max":  "claude-opus-4-7",
}
_EFFORT_ITER_CAP = {"low": 0, "medium": 0, "high": 1, "max": 3}


def _resolve_model_for_effort(effort: str) -> Optional[str]:
	if effort not in ("high", "max"):
		return None
	try:
		raw = frappe.db.get_single_value("Lazychat Settings", "vision_judge_models")
		if raw:
			data = json.loads(raw)
			if isinstance(data, dict) and data.get(effort):
				return data[effort]
	except Exception:
		pass
	return _EFFORT_DEFAULT_MODELS.get(effort)


def _strip_data_url_prefix(b64: str) -> str:
	"""Accept either a raw base64 string or a `data:image/<mime>;base64,<b64>` URL.

	Returns just the base64 payload (no prefix). Both providers' image-block
	encodings carry mime-type separately from the data, so we need to strip.
	"""
	if not isinstance(b64, str):
		return ""
	if b64.startswith("data:"):
		# Strip up through the first comma (after `;base64,`)
		_, _, rest = b64.partition(",")
		return rest.strip()
	return b64.strip()


def _extract_json_block(text: str) -> Optional[dict]:
	"""Tolerant JSON extractor. Handles:
	- bare JSON: `{...}`
	- ```json fences: ```json\n{...}\n```
	- prose-wrapped: "Here is my analysis: {...}. Done."

	Returns the parsed dict, or None if no valid JSON object could be extracted.
	"""
	if not isinstance(text, str) or not text.strip():
		return None
	# Try fenced first
	m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
	if m:
		try:
			return json.loads(m.group(1))
		except Exception:
			pass
	# Fall back to first { ... last } in the body
	s = text.find("{")
	e = text.rfind("}")
	if s == -1 or e == -1 or e <= s:
		return None
	try:
		return json.loads(text[s:e + 1])
	except Exception:
		return None


_COMPARE_SYSTEM_PROMPT = (
	"You are a visual-design QA judge. You will see TWO dashboard screenshots "
	"(REFERENCE then CANDIDATE), a user intent, and the candidate's HTML/CSS "
	"source. Grade how closely CANDIDATE matches REFERENCE for the stated intent. "
	"Return ONLY a JSON object — no prose, no markdown fences — with this shape:\n"
	"{\n"
	'  "score": 0.0-1.0,\n'
	'  "verdict": "match" | "needs_fixes",\n'
	'  "mismatches": [\n'
	'    {"category": "typography"|"color"|"layout"|"spacing"|"content"|"other",\n'
	'     "severity": "minor"|"major"|"critical",\n'
	'     "description": "...",\n'
	'     "selector_hint": "<CSS selector hint or DOM region>",\n'
	'     "fix_hint": "<concrete CSS/HTML change>"}\n'
	'  ]\n'
	"}\n"
	"Set verdict='match' when score >= 0.85; otherwise 'needs_fixes'. Be specific "
	"in fix_hint — mention concrete CSS properties / values."
)


def compare(candidate_b64: str, reference_b64: str, intent_text: str, page_source: str = "", effort: str = "medium") -> dict:
	"""Vision LLM call comparing candidate vs reference dashboard screenshots.

	Resolves a vision-capable model per Lazychat Settings.vision_judge_models
	(defaults sonnet-4-6 at high, opus-4-7 at max). Wrapped in a 30s timeout via
	ThreadPoolExecutor — on ANY failure (model misconfigured, adapter throws,
	timeout, response not parseable) returns {skipped: True, reason: "..."} so
	the calling flow never breaks.

	Returns either:
	  {score: float, verdict: "match"|"needs_fixes", mismatches: list, model: str}
	OR
	  {skipped: True, reason: str}
	"""
	if effort not in ("high", "max"):
		return {"skipped": True, "reason": f"effort={effort} skips visual judge (only high/max trigger compare)"}

	model_label = _resolve_model_for_effort(effort)
	if not model_label:
		return {"skipped": True, "reason": f"no vision model configured for effort={effort}"}

	try:
		from lazychat_erpnext.desk_assistant.providers import resolve_model

		try:
			model_doc, provider_doc, adapter = resolve_model(model_label)
		except Exception as e:
			return {"skipped": True, "reason": f"no provider configured for {model_label}: {type(e).__name__}: {str(e)[:80]}"}

		ref_b64 = _strip_data_url_prefix(reference_b64)
		cand_b64 = _strip_data_url_prefix(candidate_b64)
		if not ref_b64 or not cand_b64:
			return {"skipped": True, "reason": "missing reference_b64 or candidate_b64"}

		# Use the canonical Anthropic image block shape — both adapters accept this:
		# - AnthropicAdapter passes messages through verbatim to /messages.
		# - OpenAICompatAdapter._to_oai_messages translates {type:'image', source:{...}}
		#   into the OpenAI {type:'image_url', image_url:{url:'data:...;base64,...'}} form.
		user_blocks = [
			{
				"type": "image",
				"source": {"type": "base64", "media_type": "image/png", "data": ref_b64},
			},
			{
				"type": "image",
				"source": {"type": "base64", "media_type": "image/png", "data": cand_b64},
			},
			{
				"type": "text",
				"text": (
					f"USER INTENT:\n{(intent_text or '').strip()[:2000]}\n\n"
					f"CANDIDATE HTML/CSS SOURCE (truncated to 4000 chars):\n"
					f"{(page_source or '').strip()[:4000]}\n\n"
					"Compare REFERENCE (first image) vs CANDIDATE (second image). "
					"Return ONLY the JSON verdict object."
				),
			},
		]
		messages = [{"role": "user", "content": user_blocks}]

		def _vision_call():
			return adapter.chat(
				provider=provider_doc,
				model=model_doc,
				messages=messages,
				system=_COMPARE_SYSTEM_PROMPT,
				tools=None,
				max_tokens=2000,
			)

		with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
			fut = _pool.submit(_vision_call)
			try:
				resp = fut.result(timeout=30)
			except concurrent.futures.TimeoutError:
				return {"skipped": True, "reason": "vision LLM call timed out after 30s"}

		text_blocks = [b.get("text", "") for b in resp.content if b.get("type") == "text"]
		response_text = "\n".join(text_blocks).strip()

	except Exception as e:
		return {"skipped": True, "reason": f"vision LLM call failed: {type(e).__name__}: {str(e)[:80]}"}

	parsed = _extract_json_block(response_text)
	if not isinstance(parsed, dict):
		return {"skipped": True, "reason": f"vision response unparseable: {response_text[:120]!r}"}

	score = parsed.get("score")
	verdict = parsed.get("verdict")
	mismatches = parsed.get("mismatches")
	if not isinstance(score, (int, float)) or verdict not in ("match", "needs_fixes") or not isinstance(mismatches, list):
		return {"skipped": True, "reason": f"vision response missing required keys (score/verdict/mismatches): {response_text[:120]!r}"}

	return {
		"score": float(score),
		"verdict": verdict,
		"mismatches": mismatches,
		"model": model_label,
	}


def generate_fixes(diff_json: dict, page_doc: dict, intent_text: str, effort: str = "medium") -> dict:
	if effort not in ("high", "max"):
		return {"skipped": True, "reason": f"effort={effort} skips fix generation"}
	return {"skipped": True, "reason": "generate_fixes not yet implemented (M3.3 placeholder)"}


def iter_cap_for_effort(effort: str) -> int:
	return _EFFORT_ITER_CAP.get(effort, 0)
