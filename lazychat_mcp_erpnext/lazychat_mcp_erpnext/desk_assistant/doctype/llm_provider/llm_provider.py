import json

import frappe
from frappe.model.document import Document


class LLMProvider(Document):
	def before_validate(self):
		self._migrate_extra_headers_to_table()

	def validate(self):
		self._sync_table_to_extra_headers()

	def _migrate_extra_headers_to_table(self):
		if self.get("http_headers") and len(self.http_headers) > 0:
			return
		raw = self.extra_headers
		if not raw or not str(raw).strip():
			return
		try:
			data = json.loads(raw)
		except Exception:
			return
		if not isinstance(data, dict):
			return
		for key, val in data.items():
			self.append("http_headers", {"header_key": str(key), "header_value": str(val)})

	def _sync_table_to_extra_headers(self):
		obj = {}
		for row in self.get("http_headers") or []:
			key = (row.header_key or "").strip()
			if not key:
				continue
			obj[key] = (row.header_value or "").strip()
		self.extra_headers = json.dumps(obj, sort_keys=True) if obj else ""
