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


def compare(candidate_b64: str, reference_b64: str, intent_text: str, page_source: str = "", effort: str = "medium") -> dict:
	if effort not in ("high", "max"):
		return {"skipped": True, "reason": f"effort={effort} skips visual judge (only high/max trigger compare)"}
	return {"skipped": True, "reason": "compare not yet implemented (M3.2 placeholder)"}


def generate_fixes(diff_json: dict, page_doc: dict, intent_text: str, effort: str = "medium") -> dict:
	if effort not in ("high", "max"):
		return {"skipped": True, "reason": f"effort={effort} skips fix generation"}
	return {"skipped": True, "reason": "generate_fixes not yet implemented (M3.3 placeholder)"}


def iter_cap_for_effort(effort: str) -> int:
	return _EFFORT_ITER_CAP.get(effort, 0)
