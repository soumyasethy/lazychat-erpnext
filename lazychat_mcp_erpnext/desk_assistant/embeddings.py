"""KB vector embeddings — Tier H2 of the agentic-platform expansion.

Extends the keyword paragraph search in knowledge.py with semantic retrieval:

  1. on_file_attach (File doctype on_update hook) → enqueue process_kb_file
  2. process_kb_file: extract text → chunk ~500 tokens with 50-token overlap
     → batch-embed via the user's configured LLM provider's /v1/embeddings
     endpoint → store in Lazychat KB Chunk doctype rows
  3. hybrid_search: cosine over query embedding + RRF fusion with the existing
     keyword paragraph search → top-K. Falls back to keyword-only when no
     chunk has an embedding (graceful degradation).

Storage: each chunk's float32 vector is base64-encoded into the
embedding_blob Long Text field. 1536-dim text-embedding-3-small ≈ 8 KB
base64 / ~6 KB raw per chunk.

Dedupe: content_hash (SHA-256 of normalised chunk text) lets us skip
re-embedding when a file is re-uploaded unchanged.

Provider lookup mirrors the chat path exactly — same LLM Provider doctype,
same safe_provider_api_key resolution, same base_url. So if your chat works
with NVIDIA / OpenAI / OpenRouter / Vercel / etc, embeddings work too with
zero extra config.
"""

import base64
import hashlib
import json
import math
import re
import struct

import frappe

from lazychat_mcp_erpnext.desk_assistant.knowledge import (
	KB_DOCTYPE,
	_user_can_read_kb,
	extract_file_text,
)
from lazychat_mcp_erpnext.desk_assistant.password_utils import safe_provider_api_key

CHUNK_DOCTYPE = "Lazychat KB Chunk"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_TARGET_TOKENS = 500
DEFAULT_OVERLAP_TOKENS = 50
EMBED_BATCH_SIZE = 64  # OpenAI accepts up to 2048; 64 keeps payload size sane
EMBED_TIMEOUT_SEC = 60
TOPK_VECTOR = 20
TOPK_FINAL = 5
RRF_K = 60


# ============================================================================
# Provider resolution — find the OpenAI-compatible LLM Provider that has an
# API key, mirroring the chat path's lookup so users don't configure twice.
# ============================================================================


def _find_embedding_provider():
	"""Pick the first enabled LLM Provider with provider_type = openai_compatible
	AND a non-empty API key. Returns the doc, or None if nothing matches.

	Precedence: providers with `is_default = 1` first (matches chat-path
	behaviour), then alphabetical.
	"""
	rows = frappe.get_all(
		"LLM Provider",
		filters={"enabled": 1, "provider_type": "openai_compatible"},
		fields=["name"],
		order_by="provider_name asc",
	)
	for row in rows:
		try:
			doc = frappe.get_doc("LLM Provider", row["name"])
		except Exception:
			continue
		key = safe_provider_api_key(doc)
		if key and (doc.base_url or "").strip():
			return doc
	return None


def _embedding_endpoint_url(provider_doc):
	"""Build the /v1/embeddings URL from the provider's base_url. Handles roots
	with or without /v1 suffix the same way the chat path does in api.py."""
	root = (provider_doc.base_url or "").strip().rstrip("/")
	if re.search(r"/v\d+$", root, re.I):
		return root + "/embeddings"
	return root + "/v1/embeddings"


def _post_embeddings(provider_doc, model, texts):
	"""Single POST to the provider's /v1/embeddings endpoint. Returns
	a list of float-arrays in the same order as `texts`. Raises on failure
	so the caller can surface a clean error to the user."""
	import requests

	url = _embedding_endpoint_url(provider_doc)
	key = safe_provider_api_key(provider_doc)
	if not key:
		raise RuntimeError("LLM Provider has no API key — set one in Desk → LLM Provider")
	headers = {
		"Authorization": f"Bearer {key}",
		"Content-Type": "application/json",
	}
	# extra_headers (e.g. NVIDIA's nvcf-feature flag) live on the provider doc
	# as a child table; pull whatever the chat path uses.
	for row in (getattr(provider_doc, "extra_headers", None) or []):
		try:
			headers[row.header_key] = row.header_value
		except Exception:
			continue
	body = {"model": model, "input": texts}
	r = requests.post(url, headers=headers, json=body, timeout=EMBED_TIMEOUT_SEC)
	if not r.ok:
		# Surface upstream error body so the user can fix it (wrong model,
		# wrong key, model not in plan, etc.)
		preview = (r.text or "").strip()[:400]
		raise RuntimeError(f"/embeddings HTTP {r.status_code}: {preview}")
	payload = r.json()
	data = payload.get("data") or []
	if len(data) != len(texts):
		raise RuntimeError(
			f"/embeddings returned {len(data)} embeddings for {len(texts)} inputs"
		)
	out = []
	for row in data:
		emb = row.get("embedding")
		if not isinstance(emb, list):
			raise RuntimeError("/embeddings response missing 'embedding' field")
		out.append([float(x) for x in emb])
	return out


# ============================================================================
# Float32 base64 codec — compact + portable storage for embeddings.
# ============================================================================


def _encode_embedding(embedding):
	"""list[float] → base64-encoded little-endian float32."""
	if not embedding:
		return ""
	blob = struct.pack(f"<{len(embedding)}f", *embedding)
	return base64.b64encode(blob).decode("ascii")


def _decode_embedding(b64):
	"""base64 little-endian float32 → list[float]. Returns [] on bad input."""
	if not b64:
		return []
	try:
		blob = base64.b64decode(b64)
	except Exception:
		return []
	n = len(blob) // 4
	if n == 0:
		return []
	try:
		return list(struct.unpack(f"<{n}f", blob))
	except Exception:
		return []


def _content_hash(text):
	"""Stable hash for dedupe. Normalises whitespace so prettifying re-uploads
	don't trigger spurious re-embedding."""
	normalised = re.sub(r"\s+", " ", (text or "")).strip()
	return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


# ============================================================================
# Chunking — paragraph-aware with sentence fallback for overlong paragraphs.
# Token estimate: chars / 3.5 (good enough for English; tiktoken not required).
# ============================================================================


_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def _split_sentences(paragraph):
	parts = _SENTENCE_END_RE.split(paragraph)
	return [p.strip() for p in parts if p.strip()]


def _chunk_text(text, target_tokens=DEFAULT_TARGET_TOKENS, overlap_tokens=DEFAULT_OVERLAP_TOKENS):
	"""Split into list[str] each ≈ target_tokens. Paragraph-first, sentence-fallback.

	Overlap pulls the trailing `overlap_tokens` of the previous chunk into the
	start of the next one so a query word straddling a chunk boundary still
	matches at least one chunk. Empty input → []."""
	if not text or not text.strip():
		return []
	target_chars = int(target_tokens * 3.5)
	overlap_chars = int(overlap_tokens * 3.5)

	paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
	chunks = []
	current = ""

	def flush():
		nonlocal current
		if current.strip():
			chunks.append(current.strip())
		# Carry overlap as suffix of last chunk
		if overlap_chars > 0 and chunks:
			current = chunks[-1][-overlap_chars:]
		else:
			current = ""

	for para in paragraphs:
		if len(para) > target_chars:
			# Long paragraph — split by sentence
			for sent in _split_sentences(para):
				if len(current) + len(sent) + 2 > target_chars and current.strip():
					flush()
				current = (current + " " + sent).strip() if current else sent
			continue
		if len(current) + len(para) + 2 > target_chars and current.strip():
			flush()
		current = (current + "\n\n" + para).strip() if current else para
	if current.strip() and (not chunks or current.strip() != chunks[-1]):
		chunks.append(current.strip())
	# De-dupe consecutive identical chunks (can happen when overlap == full chunk)
	deduped = []
	for c in chunks:
		if not deduped or deduped[-1] != c:
			deduped.append(c)
	return deduped


# ============================================================================
# Indexing — extract → chunk → embed → store. Idempotent via content_hash.
# ============================================================================


def _delete_orphan_chunks(kb_name, file_name, keep_hashes):
	"""Remove chunk rows whose content_hash is no longer present in the new
	chunk set (file content changed). Run AFTER inserts so we never delete a
	chunk we still need."""
	existing = frappe.get_all(
		CHUNK_DOCTYPE,
		filters={"parent_kb": kb_name, "file_doc": file_name},
		fields=["name", "content_hash"],
	)
	for row in existing:
		if row.get("content_hash") not in keep_hashes:
			try:
				frappe.delete_doc(CHUNK_DOCTYPE, row["name"], ignore_permissions=True, force=True)
			except Exception:
				continue


def _index_file_inner(kb_name, file_doc_name):
	"""Synchronous body of process_kb_file. Returns a status dict.
	Does NOT raise — errors are captured in the status so the background
	runner can store them in the job's exc_info."""
	status = {
		"kb_name": kb_name,
		"file_doc": file_doc_name,
		"chunks_created": 0,
		"chunks_skipped": 0,
		"chunks_deleted": 0,
		"error": None,
		"embedding_model": None,
	}
	try:
		if not frappe.db.exists(KB_DOCTYPE, kb_name):
			status["error"] = f"KB not found: {kb_name}"
			return status
		if not frappe.db.exists("File", file_doc_name):
			status["error"] = f"File not found: {file_doc_name}"
			return status
		file_doc = frappe.get_doc("File", file_doc_name)
		text, fmt, err = extract_file_text(file_doc, max_chars=200_000)
		if not text:
			status["error"] = err or "empty file"
			return status

		chunks = _chunk_text(text)
		if not chunks:
			status["error"] = "no chunks produced"
			return status

		# Look up existing chunks for this (kb, file) keyed by content_hash
		existing_rows = frappe.get_all(
			CHUNK_DOCTYPE,
			filters={"parent_kb": kb_name, "file_doc": file_doc_name},
			fields=["name", "content_hash", "embedding_blob", "embedding_model", "chunk_index"],
		)
		existing_by_hash = {r["content_hash"]: r for r in existing_rows if r.get("content_hash")}

		# Plan: for each new chunk, check if hash matches an existing row.
		# Match → keep (skip embed). Miss → embed.
		new_hashes = []
		to_embed = []  # list of (chunk_index, text, content_hash) needing embedding
		for i, ch_text in enumerate(chunks):
			h = _content_hash(ch_text)
			new_hashes.append(h)
			if h in existing_by_hash and existing_by_hash[h].get("embedding_blob"):
				status["chunks_skipped"] += 1
				continue
			to_embed.append((i, ch_text, h))

		# Delete chunks that no longer exist in the new file content
		new_hash_set = set(new_hashes)
		_delete_orphan_chunks(kb_name, file_doc_name, new_hash_set)
		status["chunks_deleted"] = len(existing_rows) - len(existing_by_hash.keys() & new_hash_set)

		if not to_embed:
			# Nothing to embed — file unchanged or only chunks dropped.
			frappe.db.commit()
			return status

		# Resolve provider + model
		provider = _find_embedding_provider()
		if not provider:
			# Store chunks WITHOUT embeddings; search_kb falls back to keyword-only.
			for chunk_index, ch_text, h in to_embed:
				_upsert_chunk(kb_name, file_doc_name, chunk_index, ch_text, h, None, "")
				status["chunks_created"] += 1
			status["error"] = "no openai_compatible LLM Provider with API key configured — chunks stored without embeddings (keyword search only)"
			frappe.db.commit()
			return status

		model = DEFAULT_EMBEDDING_MODEL
		# Allow per-provider override via extra_headers row {key: lazychat_embedding_model}
		for row in (getattr(provider, "extra_headers", None) or []):
			try:
				if row.header_key == "lazychat_embedding_model" and row.header_value:
					model = row.header_value
			except Exception:
				continue
		status["embedding_model"] = model

		# Embed in batches
		for batch_start in range(0, len(to_embed), EMBED_BATCH_SIZE):
			batch = to_embed[batch_start : batch_start + EMBED_BATCH_SIZE]
			batch_texts = [t for _, t, _ in batch]
			try:
				vectors = _post_embeddings(provider, model, batch_texts)
			except Exception as e:
				# Store the chunks anyway (keyword-only); record the error.
				for chunk_index, ch_text, h in batch:
					_upsert_chunk(kb_name, file_doc_name, chunk_index, ch_text, h, None, "")
					status["chunks_created"] += 1
				status["error"] = f"embedding call failed: {e}"
				frappe.db.commit()
				return status
			for (chunk_index, ch_text, h), vector in zip(batch, vectors):
				blob = _encode_embedding(vector)
				_upsert_chunk(kb_name, file_doc_name, chunk_index, ch_text, h, model, blob)
				status["chunks_created"] += 1
		frappe.db.commit()
		return status
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), f"lazychat embeddings._index_file_inner {kb_name}/{file_doc_name}")
		status["error"] = str(e)
		return status


def _upsert_chunk(kb_name, file_doc_name, chunk_index, text, content_hash, embedding_model, embedding_blob):
	"""Insert a new Lazychat KB Chunk row. (We always insert; orphan cleanup
	runs separately so dedupe is hash-based not row-based.)"""
	doc = frappe.get_doc({
		"doctype": CHUNK_DOCTYPE,
		"parent_kb": kb_name,
		"file_doc": file_doc_name,
		"chunk_index": chunk_index,
		"text": text,
		"content_hash": content_hash,
		"embedding_model": embedding_model or "",
		"embedding_blob": embedding_blob or "",
	})
	doc.insert(ignore_permissions=True)


# ============================================================================
# Background-job entry points
# ============================================================================


def on_file_attach(doc, method=None):
	"""File doctype on_update hook. Filters to Lazychat KB attachments and
	enqueues the indexing job. Cheap — runs synchronously inside the request.

	Frappe fires on_update on EVERY save of the File doctype. We dedupe inside
	process_kb_file via content_hash, so re-saves with no content change are
	near-free (just hash compare)."""
	if not doc or doc.doctype != "File":
		return
	if doc.attached_to_doctype != KB_DOCTYPE:
		return
	if not doc.attached_to_name:
		return
	# Skip very small or zero-byte files (likely thumbnails / metadata)
	try:
		if (doc.file_size or 0) < 64:
			return
	except Exception:
		pass
	frappe.enqueue(
		"lazychat_mcp_erpnext.desk_assistant.embeddings.process_kb_file",
		queue="default",
		timeout=600,
		file_name=doc.name,
		kb_name=doc.attached_to_name,
		now=False,
	)


def process_kb_file(file_name, kb_name):
	"""Background-job target. Wraps _index_file_inner so RQ Job logs capture
	the status dict in exc_info for `list_my_jobs` to surface."""
	status = _index_file_inner(kb_name, file_name)
	# Log status to Frappe so admins can audit via Error Log / RQ Job inspect
	if status.get("error"):
		frappe.log_error(
			json.dumps(status, indent=2, default=str),
			f"lazychat embed warning {kb_name}/{file_name}",
		)
	else:
		# Successful indexing — write a short Activity Log entry
		try:
			frappe.get_doc({
				"doctype": "Comment",
				"comment_type": "Info",
				"reference_doctype": KB_DOCTYPE,
				"reference_name": kb_name,
				"content": f"Indexed file {file_name}: +{status['chunks_created']} chunks, "
				f"~{status['chunks_skipped']} skipped, model={status.get('embedding_model') or '(none)'}",
			}).insert(ignore_permissions=True)
			frappe.db.commit()
		except Exception:
			pass
	return status


def reindex_kb(kb_name):
	"""Enqueue process_kb_file for every File currently attached to the KB.
	Use after first install (existing files attached before the on_update hook
	was wired) or to force a refresh after switching embedding providers."""
	if not frappe.db.exists(KB_DOCTYPE, kb_name):
		return {"error": f"KB not found: {kb_name}"}
	if not _user_can_read_kb(kb_name):
		return {"error": f"no access to KB: {kb_name}"}
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": KB_DOCTYPE, "attached_to_name": kb_name},
		fields=["name"],
	)
	enqueued = 0
	for f in files:
		try:
			frappe.enqueue(
				"lazychat_mcp_erpnext.desk_assistant.embeddings.process_kb_file",
				queue="default",
				timeout=600,
				file_name=f["name"],
				kb_name=kb_name,
			)
			enqueued += 1
		except Exception:
			continue
	return {"ok": True, "kb_name": kb_name, "files_enqueued": enqueued}


# ============================================================================
# Hybrid retrieval — cosine over query embedding, RRF fused with keyword search
# ============================================================================


def _cosine_python(a, b):
	"""Plain-Python cosine. Acceptable for ~1000 chunks; numpy version below
	for larger KBs."""
	if not a or not b or len(a) != len(b):
		return 0.0
	dot = 0.0
	na = 0.0
	nb = 0.0
	for x, y in zip(a, b):
		dot += x * y
		na += x * x
		nb += y * y
	if na == 0 or nb == 0:
		return 0.0
	return dot / (math.sqrt(na) * math.sqrt(nb))


def _try_numpy_cosine_batch(query_vec, chunk_vecs):
	"""Batched cosine via numpy when available (Frappe ships numpy). Returns
	list[float] in same order as chunk_vecs, or None if numpy missing or shapes
	mismatch."""
	try:
		import numpy as np
	except Exception:
		return None
	try:
		q = np.asarray(query_vec, dtype=np.float32)
		c = np.asarray(chunk_vecs, dtype=np.float32)
		if c.ndim != 2 or c.shape[1] != q.shape[0]:
			return None
		q_norm = q / (np.linalg.norm(q) + 1e-10)
		c_norms = np.linalg.norm(c, axis=1, keepdims=True) + 1e-10
		c_unit = c / c_norms
		scores = c_unit @ q_norm
		return scores.tolist()
	except Exception:
		return None


def hybrid_search(query, kb_names, max_chunks=TOPK_FINAL):
	"""Cosine + keyword fused via Reciprocal Rank Fusion. Returns the same
	chunk shape as knowledge.search() with an added `score` field.

	Falls back to keyword-only when:
	  - No chunks have embeddings yet (first-time setup, no provider configured)
	  - Query embedding call fails (provider down, rate-limited, etc.)
	"""
	if not kb_names:
		return []

	# 1. Pull every chunk in scope. For very large KBs (10k+ chunks) we'd want
	#    a sharded loop or pgvector — for v1 this loads them all. The 60 KB cap
	#    on get_doc results suggests typical KBs are << 1000 chunks.
	chunk_rows = frappe.get_all(
		CHUNK_DOCTYPE,
		filters={"parent_kb": ["in", list(kb_names)]},
		fields=["name", "parent_kb", "file_doc", "chunk_index", "text", "embedding_blob"],
		order_by="parent_kb asc, file_doc asc, chunk_index asc",
		limit_page_length=10000,
	)
	if not chunk_rows:
		return []

	# 2. Compute query embedding (1 API call). Skip if no provider or no
	#    chunks have embeddings — pure keyword fallback handled below.
	have_embeddings = any(r.get("embedding_blob") for r in chunk_rows)
	query_vec = None
	if have_embeddings:
		provider = _find_embedding_provider()
		if provider:
			try:
				vectors = _post_embeddings(provider, DEFAULT_EMBEDDING_MODEL, [query])
				query_vec = vectors[0] if vectors else None
			except Exception:
				query_vec = None

	# 3. Score chunks by cosine if we have a query vector
	vector_scored = []  # [(score, chunk_row)]
	if query_vec:
		# Batched numpy path when available
		decoded_vecs = []
		row_indices = []
		for i, row in enumerate(chunk_rows):
			vec = _decode_embedding(row.get("embedding_blob") or "")
			if vec:
				decoded_vecs.append(vec)
				row_indices.append(i)
		if decoded_vecs:
			batch_scores = _try_numpy_cosine_batch(query_vec, decoded_vecs)
			if batch_scores is None:
				batch_scores = [_cosine_python(query_vec, v) for v in decoded_vecs]
			for idx, score in zip(row_indices, batch_scores):
				vector_scored.append((score, chunk_rows[idx]))
		vector_scored.sort(key=lambda x: x[0], reverse=True)
		vector_scored = vector_scored[:TOPK_VECTOR]

	# 4. Keyword scoring — count term hits per chunk (case-insensitive)
	terms = [t.lower() for t in re.findall(r"[A-Za-z0-9_]{2,}", query)]
	terms = [t for t in dict.fromkeys(terms) if len(t) >= 2]
	keyword_scored = []
	if terms:
		for row in chunk_rows:
			text_low = (row.get("text") or "").lower()
			# Score = number of distinct terms hit + small bonus for all-terms-match
			hits = sum(1 for t in terms if t in text_low)
			if hits == 0:
				continue
			bonus = 0.5 if hits == len(terms) else 0.0
			keyword_scored.append((hits + bonus, row))
		keyword_scored.sort(key=lambda x: x[0], reverse=True)
		keyword_scored = keyword_scored[:TOPK_VECTOR]

	# 5. Reciprocal Rank Fusion
	rrf = {}  # chunk_name -> {"score": float, "row": row, "vec_rank": int|None, "kw_rank": int|None}
	for rank, (_, row) in enumerate(vector_scored):
		key = row["name"]
		rrf.setdefault(key, {"score": 0.0, "row": row, "vec_rank": None, "kw_rank": None})
		rrf[key]["score"] += 1.0 / (RRF_K + rank + 1)
		rrf[key]["vec_rank"] = rank + 1
	for rank, (_, row) in enumerate(keyword_scored):
		key = row["name"]
		rrf.setdefault(key, {"score": 0.0, "row": row, "vec_rank": None, "kw_rank": None})
		rrf[key]["score"] += 1.0 / (RRF_K + rank + 1)
		rrf[key]["kw_rank"] = rank + 1

	if not rrf:
		return []

	fused = sorted(rrf.values(), key=lambda x: x["score"], reverse=True)[:max_chunks]

	# 6. Hydrate file metadata for the survivors so the agent gets file_name + URL
	file_names = list({entry["row"]["file_doc"] for entry in fused})
	file_meta = {
		f["name"]: f
		for f in frappe.get_all(
			"File",
			filters={"name": ["in", file_names]},
			fields=["name", "file_name", "file_url"],
		)
	}

	out = []
	for entry in fused:
		row = entry["row"]
		fmeta = file_meta.get(row["file_doc"], {}) or {}
		text = row.get("text") or ""
		out.append(
			{
				"kb_name": row["parent_kb"],
				"file_name": fmeta.get("file_name") or row["file_doc"],
				"file_url": fmeta.get("file_url") or "",
				"snippet": text if len(text) <= 600 else text[:600] + "…",
				"score": round(entry["score"], 4),
				"vector_rank": entry["vec_rank"],
				"keyword_rank": entry["kw_rank"],
				"chunk_id": row["name"],
			}
		)
	return out


def kb_index_status(kb_name):
	"""Return per-file embedding status for a KB. Used by get_kb_files to
	surface 'indexed' / 'pending' / 'partial' badges in the chat-ui palette
	or via the agent's tool result."""
	files = frappe.get_all(
		"File",
		filters={"attached_to_doctype": KB_DOCTYPE, "attached_to_name": kb_name},
		fields=["name", "file_name", "file_url"],
	)
	by_file = {}
	for f in files:
		chunks = frappe.get_all(
			CHUNK_DOCTYPE,
			filters={"parent_kb": kb_name, "file_doc": f["name"]},
			fields=["embedding_blob"],
		)
		total = len(chunks)
		embedded = sum(1 for c in chunks if c.get("embedding_blob"))
		if total == 0:
			status = "pending"
		elif embedded == 0:
			status = "keyword_only"
		elif embedded == total:
			status = "indexed"
		else:
			status = "partial"
		by_file[f["name"]] = {
			"file_name": f["file_name"],
			"file_url": f["file_url"],
			"chunk_count": total,
			"embedded_count": embedded,
			"status": status,
		}
	return by_file
