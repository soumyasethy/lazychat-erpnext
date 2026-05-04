import frappe
from frappe import _
from frappe.model.document import Document


class LazychatSettings(Document):
	"""Single doctype controlling the lazychat panel.

	Validation only — no business logic. Boot extension reads from this doctype
	(with site_config fallback) and exposes settings under frappe.boot.lazychat_settings.
	"""

	def validate(self):
		mcp = (self.mcp_endpoint or "").strip()
		if mcp and not mcp.startswith("/api/method/"):
			frappe.throw(
				_("MCP Endpoint must start with /api/method/ — got: {0}").format(mcp)
			)
		# Mutual exclusion check is *informational* — actual gating happens client-side
		# in lazychat_panel.bundle.js. Surfacing the warning here helps the admin notice.
		if self.legacy_widget_enabled and self.enabled:
			frappe.msgprint(
				_(
					"Legacy widget is enabled. The iframe panel will be suppressed; only the legacy vanilla-JS widget will mount."
				),
				alert=True,
				indicator="orange",
			)
