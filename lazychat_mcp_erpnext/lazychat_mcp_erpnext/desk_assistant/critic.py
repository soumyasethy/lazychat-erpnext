"""Composer-critic dual-LLM split. The composer (current chat session's
model) generates a prepare_* payload; the critic (cheap separate model
— haiku at high Effort, sonnet at max) grades it against user intent +
sample evidence. If critic disagrees with severity ≥ medium, the
iterative loop forces a re-stage with the critic's hints.

Critic uses a different model so its blind spots differ from the
composer's. Same provider stack as the composer (Anthropic /
OpenAI-compatible / OpenRouter) — configured via Lazychat Settings.

M2.2 ships the framework: prompt builder + verdict parser + STUB
critique_composition. M2.3 replaces the stub with real LLM dispatch.
"""

import json
import re


_CRITIC_MODEL_BY_EFFORT = {
	"low": None,        # skip
	"medium": None,     # skip
	"high": "claude-haiku-4-5",
	"max": "claude-sonnet-4-6",
}


def critic_model_for_effort(effort):
	"""Return the model id to use as critic for a given Effort level, or
	None if critic is skipped at that level."""
	return _CRITIC_MODEL_BY_EFFORT.get(effort or "medium")


def build_critic_prompt(intent, action, payload, evidence):
	"""Construct the critic LLM's user prompt. Plain text. Stable
	structure — `parse_critic_verdict` depends on the critic returning
	JSON only."""
	payload_json = json.dumps(payload, indent=2, default=str)[:3000]
	evidence_json = json.dumps(evidence, indent=2, default=str)[:3000]
	return f"""You are a verification critic for an ERPNext assistant. Composer
generated this {action} payload in response to user intent.

USER INTENT (verbatim):
{intent}

COMPOSED PAYLOAD:
{payload_json}

EVIDENCE (sample data from execution probe):
{evidence_json}

Grade the composition against the intent. Return ONLY valid JSON in
this shape (no prose, no markdown fences):

{{
  "verdict": "ok" | "mismatch",
  "severity": "low" | "medium" | "high",
  "mismatches": [
    {{"observation": "...", "why_it_matters": "..."}}
  ],
  "suggested_revisions": ["..."]
}}

Be SHARP. Don't rubber-stamp. Specific failure modes to check:
- Empty columns across all sample rows → likely a join bug.
- User asked for "variance" but WHERE includes matched rows → mismatch.
- Missing back-link refs in _lz_items → traceability lost.
- Long button labels that will visibly truncate → UX bug.
"""


def parse_critic_verdict(response_text):
	"""Parse critic's JSON response. Tolerates ```json fences and
	leading/trailing whitespace. Returns a dict with the standard
	verdict shape, or {error} on parse failure."""
	if not isinstance(response_text, str):
		return {"error": f"non-string response: {type(response_text).__name__}"}
	# Strip markdown fences
	m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL)
	if m:
		raw = m.group(1)
	else:
		# Find first { and last } (greedy)
		s = response_text.find('{')
		e = response_text.rfind('}')
		if s == -1 or e == -1:
			return {"error": f"no JSON object found in response: {response_text[:120]!r}"}
		raw = response_text[s:e + 1]
	try:
		obj = json.loads(raw)
	except Exception as ex:
		return {"error": f"JSON parse failed: {ex}", "raw": raw[:200]}
	# Normalize fields
	verdict = obj.get("verdict") or "ok"
	if verdict not in ("ok", "mismatch"):
		verdict = "mismatch"  # default to safe side
	severity = obj.get("severity") or "low"
	if severity not in ("low", "medium", "high"):
		severity = "medium"
	mismatches = obj.get("mismatches") or []
	if not isinstance(mismatches, list):
		mismatches = []
	suggested = obj.get("suggested_revisions") or []
	if not isinstance(suggested, list):
		suggested = []
	return {
		"verdict": verdict,
		"severity": severity,
		"mismatches": mismatches,
		"suggested_revisions": suggested,
	}


def critique_composition(intent, action, payload, evidence, *, effort="medium"):
	"""Top-level: build prompt, call critic LLM via the configured provider
	stack, parse response. Returns parsed verdict dict or {skipped: True}
	on any error or when Effort level skips the critic.

	Provider call pattern mirrors claude_bridge.py:run_agentic_turn:
	  model_doc, provider_doc, adapter = resolve_model(model_label)
	  resp = adapter.chat(provider=provider_doc, model=model_doc,
	                      messages=[...], system=..., tools=None,
	                      max_tokens=1024)
	The critic never uses tools; max_tokens 1024 is enough for the JSON blob.

	Any exception → {skipped: True, reason: "..."} so the iterative loop
	degrades gracefully instead of crashing the prepare_* response.
	"""
	model_label = critic_model_for_effort(effort)
	if not model_label:
		return {"skipped": True, "reason": f"effort={effort} skips critic"}

	prompt = build_critic_prompt(intent, action, payload, evidence)

	try:
		import frappe
		from lazychat_mcp_erpnext.desk_assistant.providers import resolve_model

		# resolve_model raises frappe.ValidationError (via frappe.throw) when
		# the model label is unknown/disabled — catch that too.
		try:
			model_doc, provider_doc, adapter = resolve_model(model_label)
		except Exception as e:
			return {"skipped": True, "reason": f"no provider configured for {model_label}: {type(e).__name__}: {str(e)[:80]}"}

		messages = [{"role": "user", "content": prompt}]
		# Cycle 11 — M4: wrap the critic LLM call in a deterministic 30s
		# timeout so a hung adapter (network stall, slow upstream) doesn't
		# block the parent prepare_* response. ThreadPoolExecutor's
		# Future.result(timeout=) is stdlib-only and matches Frappe's
		# threading model (each whitelisted method runs in its own request
		# thread already).
		import concurrent.futures
		def _critic_call():
			return adapter.chat(
				provider=provider_doc,
				model=model_doc,
				messages=messages,
				system="You are a strict verification critic. Return only the JSON verdict object with no extra prose.",
				tools=None,
				max_tokens=1024,
			)
		with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _critic_pool:
			_critic_future = _critic_pool.submit(_critic_call)
			try:
				resp = _critic_future.result(timeout=30)
			except concurrent.futures.TimeoutError:
				return {"skipped": True, "reason": "critic LLM call timed out after 30s"}

		# Extract text from AdapterResponse.content (list of blocks)
		text_blocks = [b.get("text", "") for b in resp.content if b.get("type") == "text"]
		response_text = "\n".join(text_blocks).strip()

	except Exception as e:
		return {"skipped": True, "reason": f"critic LLM call failed: {type(e).__name__}: {str(e)[:80]}"}

	parsed = parse_critic_verdict(response_text)
	if "error" in parsed:
		return {"skipped": True, "reason": f"critic response unparseable: {parsed.get('error')}"}

	parsed["model"] = model_label
	return parsed
