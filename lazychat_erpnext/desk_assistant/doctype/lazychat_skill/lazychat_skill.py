import json

import frappe
from frappe import _
from frappe.model.document import Document


class LazychatSkill(Document):
	"""A reusable agent persona = system prompt + optional restricted tool
	subset + examples. Activated via the chat-ui Skills palette; the active set
	is stored per-user in Redis under `lazychat:skills:active:<user>` (see
	desk_assistant/skills.py)."""

	def validate(self):
		# allowed_tools must be a JSON array of strings if set
		raw = (self.allowed_tools or "").strip()
		if raw:
			try:
				parsed = json.loads(raw)
			except Exception as e:
				frappe.throw(_("Allowed Tools must be valid JSON: {0}").format(e))
			if not isinstance(parsed, list) or not all(isinstance(t, str) for t in parsed):
				frappe.throw(_("Allowed Tools must be a JSON array of strings, e.g. [\"get_outstanding\", \"prepare_send_email\"]"))
		# is_public toggle is System Manager only
		if self.has_value_changed("is_public") and self.is_public and "System Manager" not in frappe.get_roles():
			frappe.throw(_("Only System Manager can publish a skill."))
