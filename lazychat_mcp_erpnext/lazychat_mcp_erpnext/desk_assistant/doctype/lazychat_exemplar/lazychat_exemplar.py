import frappe
from frappe.model.document import Document


class LazychatExemplar(Document):
	def validate(self):
		# trust_score recomputed on every save
		total = (self.success_count or 0) + (self.reject_count or 0)
		self.trust_score = (self.success_count or 0) / total if total else 0.0
