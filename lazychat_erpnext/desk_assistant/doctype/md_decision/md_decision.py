import frappe
from frappe.model.document import Document


class MDDecision(Document):
	"""A pending or resolved MD-level decision. Read by /app/md-dashboard,
	ordered by due_date when status='Pending'."""

	pass
