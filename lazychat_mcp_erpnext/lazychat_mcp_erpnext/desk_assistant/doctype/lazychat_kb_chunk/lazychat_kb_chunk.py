from frappe.model.document import Document


class LazychatKBChunk(Document):
	"""One ~500-token chunk extracted from a file attached to a Lazychat
	Knowledge Base, with its base64-encoded float32 embedding (when computed).
	Created/updated by desk_assistant.embeddings.process_kb_file run as a
	background job triggered by the File doctype's on_update hook."""

	pass
