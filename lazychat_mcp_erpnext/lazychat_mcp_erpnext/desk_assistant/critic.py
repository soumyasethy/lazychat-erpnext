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
	"""Top-level: build prompt, call critic LLM, parse response. Returns
	parsed verdict dict or {skipped: True} if Effort skips critic.

	M2.2 STUB — returns {skipped: False, verdict: "ok"} as a safe default.
	M2.3 replaces this with the real provider LLM call.
	"""
	model = critic_model_for_effort(effort)
	if not model:
		return {"skipped": True, "reason": f"effort={effort} skips critic"}
	prompt = build_critic_prompt(intent, action, payload, evidence)
	# v1 stub — M2.3 wires this to a real LLM provider.
	return {
		"skipped": False,
		"model": model,
		"prompt_chars": len(prompt),
		"verdict": "ok",  # safe default for the framework — overridden in M2.3
		"severity": "low",
		"mismatches": [],
		"suggested_revisions": [],
	}
