"""Server-side LLM proxy — production replacement for the dev-only vite-llm-proxy.

Why this exists: chat-ui's `resolveFetchTarget()` routes cross-origin LLM URLs
through `/llm-proxy` (a Vite plugin in dev). In production-embedded mode the
chat-ui dist is served by Frappe and there's no Vite plugin, so the request
returns Frappe's 404 HTML and chat-ui surfaces it as
`HTTP 400 from <NVIDIA URL>: <!DOCTYPE html>...`.

This handler mirrors `vite-llm-proxy.ts`:
  - reads x-target-url from request headers
  - validates the host against an allowlist (Lazychat Settings.llm_proxy_allowed_hosts)
  - strips disallowed inbound headers (host, content-length, accept-encoding, etc.)
  - forwards via `requests` with stream=True
  - returns a Werkzeug Response that streams chunks back chunk-by-chunk
  - 120s timeout, 504 on upstream errors, 502 on internal errors

Auth: standard Frappe whitelisted method — caller must be authenticated. Their
LLM API key (the user's BYO key from chat-ui's localStorage) goes via the
`Authorization` header which we forward verbatim. The KEY is NOT stored on the
server — just transit.
"""
import json
from urllib.parse import urlparse

import frappe
from frappe import _


# Headers we never forward upstream (vite-llm-proxy parity, lines 42–53).
# Critically: accept-encoding is stripped to avoid SSE buffering when upstreams
# return brotli/zstd-encoded streaming responses (Werkzeug + python requests don't
# transparently decode mid-stream).
#
# `authorization` is also denied because Frappe's auth middleware processes it
# (Frappe-specific token / API-key / OAuth Bearer formats) BEFORE this handler
# runs. The user's actual LLM API key arrives via the alternate header
# `x-target-authorization` (and `x-target-api-key`) which Frappe leaves alone.
_DENY_HEADERS = {
	"host",
	"content-length",
	"connection",
	"x-target-url",
	"x-target-authorization",
	"x-target-api-key",
	"x-target-api-key-header",
	"authorization",
	"x-frappe-csrf-token",
	"x-frappe-cmd",
	"origin",
	"referer",
	"accept-encoding",
	"cookie",
	# Browser fetch metadata — never useful upstream
}
_DENY_PREFIXES = ("sec-fetch-", "sec-ch-", "x-frappe-")

_DEFAULT_ALLOWED_HOSTS = [
	"api.anthropic.com",
	"api.openai.com",
	"integrate.api.nvidia.com",
	"openrouter.ai",
	"ai-gateway.vercel.sh",
	"api.together.xyz",
	"api.groq.com",
	"api.fireworks.ai",
	"generativelanguage.googleapis.com",
	"api.deepseek.com",
	"api.mistral.ai",
	"api.cohere.com",
	"api.x.ai",
]


def _allowed_hosts() -> list[str]:
	"""Resolve the host allowlist via Lazychat Settings (with fallback default)."""
	from lazychat_erpnext.desk_assistant.boot import get_lazychat_settings

	raw = get_lazychat_settings().get("llm_proxy_allowed_hosts")
	if isinstance(raw, list):
		return [str(h).strip().lower() for h in raw if h]
	if isinstance(raw, str) and raw.strip():
		try:
			parsed = json.loads(raw)
			if isinstance(parsed, list):
				return [str(h).strip().lower() for h in parsed if h]
		except json.JSONDecodeError:
			# Treat newline/comma-separated as a fallback parse
			items = []
			for line in raw.replace(",", "\n").splitlines():
				line = line.strip()
				if line:
					items.append(line.lower())
			if items:
				return items
	return list(_DEFAULT_ALLOWED_HOSTS)


def _filter_headers(incoming) -> dict[str, str]:
	"""Drop hop-by-hop + browser-specific headers, keep auth + content-type."""
	out: dict[str, str] = {}
	for key, value in incoming.items():
		k = key.lower()
		if k in _DENY_HEADERS:
			continue
		if any(k.startswith(p) for p in _DENY_PREFIXES):
			continue
		if value is None:
			continue
		out[key] = value
	return out


def _make_response(generator, *, status: int = 200, mimetype: str | None = None, extra_headers: dict[str, str] | None = None):
	from werkzeug.wrappers import Response

	resp = Response(generator, status=status, mimetype=mimetype, direct_passthrough=True)
	resp.headers["Cache-Control"] = "no-cache, no-transform"
	resp.headers["X-Accel-Buffering"] = "no"
	# Tell the browser to release the socket after this response.
	#
	# Why: SSE streams that finish via [DONE] hold a keep-alive socket in
	# Chrome's HTTP/1.1 connection pool (max 6 per origin). When the chat-ui
	# kept LLM streams alive then immediately POSTed mcp.handle for tool
	# dispatch, the new fetch could not get a slot — it queued for ~55s and
	# Chrome eventually rejected it with a generic `TypeError: Failed to
	# fetch`. Forcing close on the LLM proxy response evicts that slot the
	# instant the upstream completes, so the very next mcp.handle fetch
	# succeeds in milliseconds. Keep-alive on a streaming proxy buys you
	# nothing — every LLM turn opens a fresh connection anyway.
	resp.headers["Connection"] = "close"
	# CORS is handled by Frappe's `allow_cors` middleware (site_config). Setting
	# ACAO=* here would duplicate the header (`*, <origin>`) and the browser
	# rejects the response — only one ACAO value is allowed when credentials
	# are involved. Same-origin (production) needs no CORS header at all.
	if extra_headers:
		for k, v in extra_headers.items():
			resp.headers[k] = v
	frappe.local.response = resp
	return resp


_PROXY_PATH_API = "/api/method/lazychat_erpnext.desk_assistant.llm_proxy.handle"
_PROXY_PATH_LEGACY = "/llm-proxy"


def trace_legacy_proxy_hit():
	"""before_request hook: log every request that hits either proxy path.

	Fires BEFORE Frappe's auth/csrf check, so we capture even rejected requests.
	If chat-ui keeps failing without a handler-entry log, this tells us why:
	  - path=/llm-proxy → chat-ui on stale bundle (dev fallback URL)
	  - path=/api/method/... but no entry log later → Frappe rejected at auth/csrf BEFORE the handler ran
	"""
	try:
		req = frappe.request
		path = (req.path or "").rstrip("/")
		if path != _PROXY_PATH_LEGACY and not path.endswith(_PROXY_PATH_API.rstrip("/")):
			return
		legacy = path == _PROXY_PATH_LEGACY or path.endswith("/llm-proxy")
		title = "lazychat llm_proxy: legacy /llm-proxy hit" if legacy else "lazychat llm_proxy: api path pre-auth trace"
		frappe.log_error(
			message=(
				f"path={path}\n"
				f"method={req.method}\n"
				f"target_url={req.headers.get('x-target-url', '(missing)')[:120]}\n"
				f"has_authorization={bool(req.headers.get('authorization'))}\n"
				f"has_x_target_authorization={bool(req.headers.get('x-target-authorization'))}\n"
				f"has_x_frappe_csrf_token={bool(req.headers.get('x-frappe-csrf-token'))}\n"
				f"has_cookie_sid={'sid=' in (req.headers.get('cookie') or '')}\n"
				f"user_agent={req.headers.get('user-agent', '?')[:120]}\n"
				f"referer={req.headers.get('referer', '(none)')[:200]}\n"
				f"all_header_keys={sorted({k.lower() for k in req.headers.keys()})}"
			),
			title=title,
		)
	except Exception:
		pass


@frappe.whitelist(methods=["POST", "OPTIONS"], allow_guest=False)
def handle():
	"""Forward an arbitrary POST to the LLM URL declared in `x-target-url`.

	Streams the response back chunk-by-chunk so SSE works.
	Allowlist-gated: only target hosts in Lazychat Settings.llm_proxy_allowed_hosts pass.
	"""
	import requests

	req = frappe.request

	# Diagnostic: log every entry so we can see what the browser is sending.
	# Writes to Error Log so it's visible at /app/error-log.
	try:
		hdr_keys = sorted({k.lower() for k in req.headers.keys()})
		has_auth = "authorization" in hdr_keys
		has_target_auth = "x-target-authorization" in hdr_keys
		has_target_url = "x-target-url" in hdr_keys
		target_url_preview = req.headers.get("x-target-url", "(missing)")[:120]
		body_size = len(req.get_data(cache=True, as_text=False) or b"")
		frappe.log_error(
			message=(
				f"method={req.method}\n"
				f"target_url={target_url_preview}\n"
				f"has_authorization={has_auth} has_x_target_authorization={has_target_auth} has_x_target_url={has_target_url}\n"
				f"body_bytes={body_size}\n"
				f"all_header_keys={hdr_keys}\n"
				f"user={getattr(frappe.session, 'user', '?')}"
			),
			title="lazychat llm_proxy: entry",
		)
	except Exception:
		pass

	# OPTIONS preflight — only relevant when chat-ui is on a different origin
	if req.method == "OPTIONS":
		return _make_response(
			b"",
			status=204,
			extra_headers={
				"Access-Control-Allow-Methods": "POST, OPTIONS",
				"Access-Control-Allow-Headers": "*",
				"Access-Control-Max-Age": "86400",
			},
		)

	target_url = req.headers.get("x-target-url") or req.args.get("target_url") or ""
	target_url = target_url.strip()
	if not target_url:
		return _make_response(b"Missing x-target-url header", status=400, mimetype="text/plain")

	try:
		parsed = urlparse(target_url)
	except Exception:
		return _make_response(b"Invalid target URL", status=400, mimetype="text/plain")
	if parsed.scheme not in ("http", "https"):
		return _make_response(b"Target URL must be http(s)", status=400, mimetype="text/plain")

	host = (parsed.hostname or "").lower()
	allowed = _allowed_hosts()
	# Allow exact match OR subdomain match (e.g. "openrouter.ai" matches "abc.openrouter.ai")
	if not (host in allowed or any(host.endswith("." + a) for a in allowed)):
		return _make_response(
			f"Target host '{host}' not in allowlist. Edit Desk → Lazychat Settings → llm_proxy_allowed_hosts.".encode("utf-8"),
			status=403,
			mimetype="text/plain",
		)

	headers = _filter_headers(req.headers)
	# Re-attach the upstream auth: chat-ui sends the user's LLM API key via
	# `x-target-authorization` (or x-target-api-key + x-target-api-key-header)
	# because Frappe's auth middleware mangles a real `Authorization` header.
	# We rename here so the upstream LLM sees the standard form.
	tgt_auth = req.headers.get("x-target-authorization")
	if tgt_auth:
		headers["Authorization"] = tgt_auth
	tgt_apikey = req.headers.get("x-target-api-key")
	tgt_apikey_header = req.headers.get("x-target-api-key-header") or "x-api-key"
	if tgt_apikey:
		headers[tgt_apikey_header] = tgt_apikey
	# Body — read raw; Frappe whitelisted methods may already have parsed form_dict but get_data returns the raw stream
	body = req.get_data(cache=False, as_text=False) or b""

	try:
		upstream = requests.post(
			target_url,
			headers=headers,
			data=body,
			stream=True,
			timeout=120,
		)
	except requests.exceptions.Timeout as e:
		return _make_response(f"Upstream error: timeout ({e})".encode("utf-8"), status=504, mimetype="text/plain")
	except requests.exceptions.ConnectionError as e:
		return _make_response(f"Upstream error: connection ({e})".encode("utf-8"), status=504, mimetype="text/plain")
	except Exception as e:
		frappe.log_error(frappe.get_traceback(), "lazychat_erpnext.llm_proxy")
		return _make_response(f"Proxy error: {e}".encode("utf-8"), status=502, mimetype="text/plain")

	upstream_ct = upstream.headers.get("content-type") or "application/octet-stream"
	upstream_status = upstream.status_code

	def stream_chunks():
		try:
			for chunk in upstream.iter_content(chunk_size=4096):
				if chunk:
					yield chunk
		except Exception as e:
			# Client disconnected or upstream died mid-stream — log + bail
			frappe.log_error(f"llm_proxy stream error: {e}", "lazychat_erpnext.llm_proxy")
		finally:
			try:
				upstream.close()
			except Exception:
				pass

	return _make_response(stream_chunks(), status=upstream_status, mimetype=upstream_ct)
