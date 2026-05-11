import frappe
from frappe import _
from frappe.model.document import Document


class LazychatKnowledgeBase(Document):
	"""A collection of attached files the agent can search via the search_kb
	tool. ACL: System Manager full + All read; users see is_public=1 KBs and
	their own (owner)."""

	def validate(self):
		if self.has_value_changed("is_public") and self.is_public and "System Manager" not in frappe.get_roles():
			frappe.throw(_("Only System Manager can publish a knowledge base."))
