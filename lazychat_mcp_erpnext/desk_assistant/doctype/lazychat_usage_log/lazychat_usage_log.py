"""Lazychat Usage Log doctype controller. No business logic — Frappe creates
the table from the JSON schema. Validation lives in the API endpoints
(api.record_usage) and the agent paths that write here directly."""
import frappe
from frappe.model.document import Document


class LazychatUsageLog(Document):
	pass
