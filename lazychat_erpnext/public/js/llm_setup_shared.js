// Shared helpers for LLM Provider / LLM Model desk forms (cURL import).
(function () {
	"use strict";

	frappe.provide("lazychat_erpnext.llm_setup");

	function stripQuotes(s) {
		const t = (s || "").trim();
		if ((t[0] === '"' && t[t.length - 1] === '"') || (t[0] === "'" && t[t.length - 1] === "'")) {
			return t.slice(1, -1);
		}
		return t;
	}

	function parseHeadersFromCurl(text) {
		const headers = {};
		const norm = text.replace(/\\\r?\n/g, " ");
		const bits = norm.split(/\s+-H\s+/i);
		for (let i = 1; i < bits.length; i++) {
			let h = bits[i].trim();
			const stop = h.search(/\s+--|\s+-[a-z]/i);
			if (stop > 0) h = h.slice(0, stop).trim();
			let inner = h;
			if (
				(h[0] === '"' && h[h.length - 1] === '"') ||
				(h[0] === "'" && h[h.length - 1] === "'")
			) {
				inner = stripQuotes(h);
			}
			const idx = inner.indexOf(":");
			if (idx > 0) {
				const k = inner.slice(0, idx).trim();
				const v = inner.slice(idx + 1).trim();
				if (k) headers[k] = v;
			}
		}
		return headers;
	}

	function findUrlInCurl(text) {
		const flat = text.replace(/\\\r?\n/g, " ").trim();
		const um = flat.match(/\b--url\s+(['"]?)(https?:\/\/[^\s'"]+)\1/i);
		if (um) return um[2];
		const quoted = flat.match(/['"](https?:\/\/[^'"]+)['"]/);
		if (quoted) return quoted[1];
		const bare = flat.match(/\b(https?:\/\/[^\s'"]+)/);
		return bare ? bare[1] : "";
	}

	function endpointToBaseUrl(url) {
		try {
			const u = new URL(url);
			let path = (u.pathname || "").replace(/\/$/, "") || "";
			const suffixes = ["/v1/chat/completions", "/chat/completions", "/v1/messages", "/messages"];
			for (const suf of suffixes) {
				if (path.endsWith(suf)) {
					path = path.slice(0, -suf.length) || "";
					break;
				}
			}
			if (path.endsWith("/chat")) path = path.slice(0, -"/chat".length);
			const basePath = path ? (path.startsWith("/") ? path : "/" + path) : "";
			return (u.origin + basePath).replace(/\/$/, "") || u.origin;
		} catch (e) {
			return url;
		}
	}

	lazychat_erpnext.llm_setup.parseCurl = function (raw) {
		const text = (raw || "").trim();
		if (!text) return { error: __("Paste a cURL command first.") };
		const url = findUrlInCurl(text);
		if (!url) return { error: __("Could not find an http(s) URL in the cURL.") };
		const headers = parseHeadersFromCurl(text);
		let api_key = "";
		const auth = headers.Authorization || headers.authorization;
		if (auth && /^Bearer\s+/i.test(auth)) {
			api_key = auth.replace(/^Bearer\s+/i, "").trim();
			delete headers.Authorization;
			delete headers.authorization;
		}
		const xkey = headers["x-api-key"] || headers["X-Api-Key"];
		if (xkey && !api_key) {
			api_key = xkey;
			delete headers["x-api-key"];
			delete headers["X-Api-Key"];
		}
		const base_url = endpointToBaseUrl(url);
		return { base_url, api_key, headers, url };
	};

	lazychat_erpnext.llm_setup.applyParsedToProviderForm = function (frm, parsed) {
		if (parsed.error) {
			frappe.msgprint({ title: __("cURL"), message: parsed.error, indicator: "red" });
			return;
		}
		if (parsed.base_url) frm.set_value("base_url", parsed.base_url);
		if (parsed.api_key) frm.set_value("api_key", parsed.api_key);
		frm.clear_table("http_headers");
		const keys = Object.keys(parsed.headers || {});
		keys.forEach((k) => {
			const row = frm.add_child("http_headers");
			row.header_key = k;
			row.header_value = parsed.headers[k];
		});
		frm.refresh_field("http_headers");
		frappe.show_alert({ message: __("Filled from cURL"), indicator: "green" });
	};

	/** Add desk styling hook for cURL / setup modals (UI polish). */
	lazychat_erpnext.llm_setup.wrapSetupDialog = function (d) {
		const orig = d.show;
		d.show = function () {
			const out = orig.apply(this, arguments);
			requestAnimationFrame(() => {
				try {
					if (d.$wrapper) d.$wrapper.find(".modal-dialog").first().addClass("llm-setup-dialog");
				} catch (e) {
					/* no-op */
				}
			});
			return out;
		};
		return d;
	};
})();
