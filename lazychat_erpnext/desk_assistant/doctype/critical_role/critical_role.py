import frappe
from frappe.model.document import Document


class CriticalRole(Document):
	"""A critical/watched open hiring slot tracked on the MD Dashboard.
	Standalone of standard Job Opening to keep MD-facing schema minimal."""

	pass
