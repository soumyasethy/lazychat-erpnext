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


_GENERATE_FIXES_SYSTEM_PROMPT = (
	"You are a frontend code-fix generator. Given a visual-diff JSON (from a "
	"visual-judge that compared a candidate Desk Page to a reference design) "
	"and the current Page's source fields (style, content, script), produce a "
	"PATCH that — when merged into the Page doc — resolves the mismatches "
	"flagged in the diff.\n"
	"Return ONLY a JSON object — no prose, no markdown fences — with this shape:\n"
	"{\n"
	'  "patch": {\n'
	'    "style"?: "<replacement CSS for the Page.style field>",\n'
	'    "content"?: "<replacement HTML for the Page.content field>",\n'
	'    "script"?: "<replacement JS for the Page.script field>"\n'
	"  }\n"
	"}\n"
	"Include ONLY the keys you actually want to change. Each value is the full "
	"replacement contents for that Page field. Do NOT emit selectors or partial "
	"snippets — emit complete fields ready to overwrite. Stay within "
	"Frappe Desk Page conventions (the script body wraps `frappe.pages[...]`)."
)

# Patch keys must be drawn from this whitelist — feeds directly into
# prepare_update_doc on the Page record.
_ALLOWED_PATCH_KEYS = {"style", "content", "script"}


def generate_fixes(diff_json: dict, page_doc: dict, intent_text: str, effort: str = "medium") -> dict:
	"""Text-only LLM call producing a patch_dict for prepare_update_doc.

	Reads the diff JSON from compare() + the current Page doc fields,
	asks the LLM for a {style?, content?, script?} replacement patch.
	Whitelisted patch keys (defense against the LLM emitting other doc keys).
	Wrapped in a 60s timeout — longer than compare's 30s because large page
	bodies need more output tokens.

	Returns either:
	  {patch: {style?, content?, script?}, model: str}
	OR
	  {skipped: True, reason: str}
	"""
	if effort not in ("high", "max"):
		return {"skipped": True, "reason": f"effort={effort} skips fix generation"}

	model_label = _resolve_model_for_effort(effort)
	if not model_label:
		return {"skipped": True, "reason": f"no model configured for effort={effort}"}

	if not isinstance(diff_json, dict) or not diff_json.get("mismatches"):
		return {"skipped": True, "reason": "diff_json missing or has no mismatches to fix"}

	page_doc = page_doc or {}

	try:
		from lazychat_erpnext.desk_assistant.providers import resolve_model

		try:
			model_doc, provider_doc, adapter = resolve_model(model_label)
		except Exception as e:
			return {"skipped": True, "reason": f"no provider configured for {model_label}: {type(e).__name__}: {str(e)[:80]}"}

		# Compact diff JSON for the prompt — trim mismatch lists if very large
		mismatches = diff_json.get("mismatches") or []
		if isinstance(mismatches, list) and len(mismatches) > 20:
			mismatches = mismatches[:20]
		diff_compact = {
			"score": diff_json.get("score"),
			"verdict": diff_json.get("verdict"),
			"mismatches": mismatches,
		}

		current_style = (page_doc.get("style") or "")[:6000]
		current_content = (page_doc.get("content") or "")[:6000]
		current_script = (page_doc.get("script") or "")[:6000]
		page_name = page_doc.get("name") or "<unnamed>"

		user_text = (
			f"USER INTENT:\n{(intent_text or '').strip()[:2000]}\n\n"
			f"PAGE: {page_name}\n\n"
			f"VISUAL DIFF (from visual_judge.compare):\n{json.dumps(diff_compact, indent=2, default=str)[:4000]}\n\n"
			f"CURRENT Page.style:\n{current_style}\n\n"
			f"CURRENT Page.content:\n{current_content}\n\n"
			f"CURRENT Page.script:\n{current_script}\n\n"
			"Produce the JSON patch that resolves these mismatches."
		)
		messages = [{"role": "user", "content": user_text}]

		def _fixes_call():
			return adapter.chat(
				provider=provider_doc,
				model=model_doc,
				messages=messages,
				system=_GENERATE_FIXES_SYSTEM_PROMPT,
				tools=None,
				max_tokens=4096,
			)

		# 60s — longer than compare's 30s. Patch generation produces large
		# output (full replacement page fields) so output token volume drives
		# wall-clock latency.
		with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _pool:
			fut = _pool.submit(_fixes_call)
			try:
				resp = fut.result(timeout=60)
			except concurrent.futures.TimeoutError:
				return {"skipped": True, "reason": "fix-generation LLM call timed out after 60s"}

		text_blocks = [b.get("text", "") for b in resp.content if b.get("type") == "text"]
		response_text = "\n".join(text_blocks).strip()

	except Exception as e:
		return {"skipped": True, "reason": f"fix-generation LLM call failed: {type(e).__name__}: {str(e)[:80]}"}

	parsed = _extract_json_block(response_text)
	if not isinstance(parsed, dict):
		return {"skipped": True, "reason": f"fix-gen response unparseable: {response_text[:120]!r}"}

	patch_raw = parsed.get("patch")
	if not isinstance(patch_raw, dict) or not patch_raw:
		return {"skipped": True, "reason": "fix-gen response missing non-empty 'patch' object"}

	# Whitelist patch keys — defense against the LLM trying to overwrite arbitrary
	# Page doc fields (route, parent_page, etc.). Anything outside style/content/
	# script gets stripped silently.
	patch_clean = {k: v for k, v in patch_raw.items() if k in _ALLOWED_PATCH_KEYS and isinstance(v, str)}
	if not patch_clean:
		return {"skipped": True, "reason": "fix-gen patch had no whitelisted keys (style/content/script)"}

	return {
		"patch": patch_clean,
		"model": model_label,
	}


def iter_cap_for_effort(effort: str) -> int:
	return _EFFORT_ITER_CAP.get(effort, 0)
