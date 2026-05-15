import frappe
from frappe.model.document import Document


class MDRisk(Document):
	"""One executive risk tracked on the MD Dashboard's Top Risks list.
	Treated as 'open' when resolved_date is null."""

	pass
