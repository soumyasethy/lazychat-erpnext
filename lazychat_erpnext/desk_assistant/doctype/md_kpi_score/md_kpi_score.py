import frappe
from frappe.model.document import Document


class MDKPIScore(Document):
	"""One row of the MD's Balanced Scorecard. Edited via /app/md-kpi-score/<name>.
	Read by /app/md-dashboard which groups rows by perspective and renders status counts."""

	pass
