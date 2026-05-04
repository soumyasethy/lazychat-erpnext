/**
 * ERPNext Desk — lazychat-ai iframe panel.
 * Mounts a fixed-position right slide-out hosting the lazychat React UI.
 * Speaks the lazychat postMessage protocol (envelope {v:1, src, id, type, payload}).
 * Proxies agentRequest -> lazychat_mcp_erpnext.desk_assistant.api.send_message_stream (SSE)
 * with batch send_message as fallback, replaying its events as a fake stream.
 *
 * After changing this file: bench build --app lazychat_mcp_erpnext && bench --site <site> clear-cache
 */
(function () {
	"use strict";

	const STORAGE_OPEN = "lazychat_panel_open";
	const STORAGE_WIDTH = "lazychat_panel_width";
	const STORAGE_SID_MAP = "lazychat_sid_to_convo";
	const WIDTH_MIN = 320;
	const WIDTH_MAX_RATIO = 0.7;
	const WIDTH_DEFAULT = 420;

	function deskUser() {
		if (window.frappe && frappe.session && frappe.session.user) return frappe.session.user;
		return null;
	}

	function isDeskShell() {
		if (window.app === true) return true;
		const p = window.location.pathname || "";
		return p === "/app" || p.startsWith("/app/");
	}

	function deskRoute() {
		const r = (window.frappe && frappe.get_route && frappe.get_route()) || [];
		const view = r[0] || null; // "Form" | "List" | "Workspaces" | "Tree" | "Report" | ...
		const doctype = (view === "Form" || view === "List" || view === "Tree" || view === "Report") ? r[1] : null;
		const docname = view === "Form" ? r[2] : null;
		const ctx = {
			route: r,
			view: view,
			user: deskUser(),
			doctype: doctype,
			docname: docname,
		};
		// On a Form view, surface the in-memory doc so the LLM can answer "summarize this"
		// without needing to call get_doc first. cur_frm is set by Frappe's form controller.
		if (view === "Form" && window.cur_frm && window.cur_frm.doc) {
			const d = window.cur_frm.doc;
			ctx.current_doc = {
				name: d.name,
				doctype: d.doctype,
				owner: d.owner,
				modified: d.modified,
				docstatus: d.docstatus,
				workflow_state: d.workflow_state || null,
				status: d.status || null,
				dirty: !!window.cur_frm.is_dirty && window.cur_frm.is_dirty(),
			};
			// Title field varies by doctype; Frappe stashes the resolved title on the form
			if (window.cur_frm.meta && window.cur_frm.meta.title_field) {
				ctx.current_doc.title_field = window.cur_frm.meta.title_field;
				ctx.current_doc.title = d[window.cur_frm.meta.title_field];
			}
		}
		// On a List view, surface selected rows (list view tracks via cur_list)
		if (view === "List" && window.cur_list) {
			try {
				const selected = (window.cur_list.get_checked_items && window.cur_list.get_checked_items()) || [];
				if (selected.length) {
					ctx.selected_rows = selected.map((r) => r.name).slice(0, 50);
				}
			} catch (_e) { /* ignore */ }
		}
		return ctx;
	}

	function resolveIframeSrc() {
		// Default: same-origin bundled SPA (no port dependency, works on any bench).
		// Override via site_config.json `lazychat_iframe_src` for chat-ui HMR dev.
		const boot = (window.frappe && frappe.boot) || {};
		if (boot.lazychat_iframe_src) return boot.lazychat_iframe_src;
		return "/assets/lazychat_mcp_erpnext/lazychat_dist/index.html?frame=sidebar";
	}

	function originOf(url) {
		try {
			return new URL(url, window.location.href).origin;
		} catch (_e) {
			return window.location.origin;
		}
	}

	function uuid() {
		return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
			const r = (Math.random() * 16) | 0;
			return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
		});
	}

	function readSidMap() {
		try {
			return JSON.parse(localStorage.getItem(STORAGE_SID_MAP) || "{}");
		} catch (_e) {
			return {};
		}
	}
	function writeSidMap(m) {
		try {
			localStorage.setItem(STORAGE_SID_MAP, JSON.stringify(m));
		} catch (_e) {
			/* ignore */
		}
	}

	function csrf() {
		return (window.frappe && frappe.csrf_token) || "";
	}

	/* ------------------------------------------------------------------
	 * postMessage envelope helpers — mirror packages/types/src/postmessage.ts
	 * ------------------------------------------------------------------ */
	function makeBridge(iframe, iframeOrigin) {
		const listeners = new Map(); // type -> Set<fn>

		function send(type, payload, id) {
			if (!iframe.contentWindow) return;
			const env = { v: 1, src: "host", id: id || uuid(), type, payload };
			iframe.contentWindow.postMessage(env, iframeOrigin);
		}

		function on(type, cb) {
			if (!listeners.has(type)) listeners.set(type, new Set());
			listeners.get(type).add(cb);
			return () => listeners.get(type).delete(cb);
		}

		function handle(ev) {
			if (ev.source !== iframe.contentWindow) return;
			if (ev.origin !== iframeOrigin) return;
			const env = ev.data;
			if (!env || env.v !== 1 || env.src !== "iframe") return;
			const set = listeners.get(env.type);
			if (set) set.forEach((cb) => cb(env.payload, env));
		}

		window.addEventListener("message", handle);
		return { send, on, destroy: () => window.removeEventListener("message", handle) };
	}

	/* ------------------------------------------------------------------
	 * Agent path — runs a single user turn against lazychat_mcp_erpnext.
	 * Intercepts /commit slash commands; tries SSE first; falls back to batch + event replay.
	 * ------------------------------------------------------------------ */
	function runCommitCommand(token, emit) {
		emit.chunk("Committing token `" + token + "` ...\n\n");
		fetch("/api/method/lazychat_mcp_erpnext.desk_assistant.api.commit_prepared_action", {
			method: "POST",
			credentials: "include",
			headers: {
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": csrf(),
			},
			body: JSON.stringify({ token: token }),
		})
			.then(function (r) { return r.json(); })
			.then(function (j) {
				const m = (j && j.message) || {};
				if (m.ok) {
					const link = m.link ? "[" + m.doctype + "/" + m.name + "](" + m.link + ")" : (m.doctype + "/" + m.name);
					emit.chunk("**Done** — " + (m.action || "applied") + " " + link + "\n");
				} else {
					emit.chunk("**Failed** — " + (m.error || "Unknown error") + "\n");
				}
				emit.done("stop");
			})
			.catch(function (err) { emit.error(String(err && err.message ? err.message : err), true); });
	}

	function lastUserText(messages) {
		const lastUser = (messages || []).filter(function (m) { return m.role === "user"; }).slice(-1)[0];
		return lastUser ? String(lastUser.content || "") : "";
	}

	function runAgentTurn(req, emit, getConvoId, setConvoId) {
		const userText = lastUserText(req.messages);
		const commitMatch = /^\s*\/commit\s+(\S+)\s*$/.exec(userText);
		if (commitMatch) {
			runCommitCommand(commitMatch[1], emit);
			return;
		}
		const message = (req.messages || [])
			.filter((m) => m.role === "user")
			.map((m) => m.content)
			.join("\n\n");
		const convoId = getConvoId(req.sid);
		const ctx = deskRoute();
		const modelLabel = req.model && req.model !== "default" ? req.model : null;

		const sseUrl = "/api/method/lazychat_mcp_erpnext.desk_assistant.api.send_message_stream";
		const body = JSON.stringify({
			message,
			conversation_id: convoId,
			context: JSON.stringify(ctx),
			model_label: modelLabel,
			confirmed_writes: !!req.params?.confirmedWrites,
		});

		const ctrl = new AbortController();
		req.signal.addEventListener("abort", () => ctrl.abort(), { once: true });

		fetch(sseUrl, {
			method: "POST",
			credentials: "include",
			headers: {
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": csrf(),
				Accept: "text/event-stream",
			},
			body,
			signal: ctrl.signal,
		})
			.then(async (res) => {
				if (res.status === 404) {
					/* SSE endpoint not deployed yet — fall back to batch */
					return runBatchFallback(message, convoId, ctx, modelLabel, req, emit, setConvoId);
				}
				if (!res.ok) throw new Error(`HTTP ${res.status}`);
				const ct = res.headers.get("content-type") || "";
				if (!ct.includes("text/event-stream")) {
					/* Server returned JSON despite the Accept header — treat as batch */
					const data = await res.json();
					return replayBatchEvents(data, req, emit, setConvoId);
				}
				await readSseStream(res, req, emit, setConvoId);
			})
			.catch((err) => {
				if (ctrl.signal.aborted) {
					emit.done("cancelled");
				} else {
					emit.error(String(err && err.message ? err.message : err), true);
				}
			});
	}

	function runBatchFallback(message, convoId, ctx, modelLabel, req, emit, setConvoId) {
		const url = "/api/method/lazychat_mcp_erpnext.desk_assistant.api.send_message";
		return fetch(url, {
			method: "POST",
			credentials: "include",
			headers: {
				"Content-Type": "application/json",
				"X-Frappe-CSRF-Token": csrf(),
			},
			body: JSON.stringify({
				message,
				conversation_id: convoId,
				context: JSON.stringify(ctx),
				model_label: modelLabel,
				confirmed_writes: !!req.params?.confirmedWrites,
			}),
		})
			.then((r) => r.json())
			.then((j) => {
				const data = (j && j.message) || {};
				replayBatchEvents(data, req, emit, setConvoId);
			});
	}

	function replayBatchEvents(data, req, emit, setConvoId) {
		if (data.conversation_id) setConvoId(req.sid, data.conversation_id);
		const events = data.events || [];
		for (const ev of events) {
			if (ev.type === "text_delta") {
				emit.chunk(ev.delta || "");
			} else if (ev.type === "tool_use") {
				emit.chunk(`\n\n> _Calling \`${ev.name}\`_\n\n`);
			} else if (ev.type === "tool_result") {
				/* swallow — the assistant will narrate the result on its next text_delta */
			}
		}
		emit.done("stop");
	}

	async function readSseStream(res, req, emit, setConvoId) {
		const reader = res.body.getReader();
		const decoder = new TextDecoder();
		let buf = "";
		while (true) {
			const { done, value } = await reader.read();
			if (done) break;
			buf += decoder.decode(value, { stream: true });
			let idx;
			while ((idx = buf.indexOf("\n\n")) >= 0) {
				const block = buf.slice(0, idx);
				buf = buf.slice(idx + 2);
				const lines = block.split("\n");
				let event = "message";
				let data = "";
				for (const ln of lines) {
					if (ln.startsWith("event:")) event = ln.slice(6).trim();
					else if (ln.startsWith("data:")) data += ln.slice(5).trim();
				}
				if (!data) continue;
				let payload;
				try {
					payload = JSON.parse(data);
				} catch (_e) {
					continue;
				}
				if (event === "text_delta") {
					emit.chunk(payload.delta || "");
				} else if (event === "tool_use") {
					emit.chunk(`\n\n> _Calling \`${payload.name}\`_\n\n`);
				} else if (event === "conversation") {
					if (payload.conversation_id) setConvoId(req.sid, payload.conversation_id);
				} else if (event === "error") {
					emit.error(payload.message || "Unknown error", payload.retryable !== false);
					return;
				} else if (event === "done") {
					emit.done(payload.finishReason || "stop");
					return;
				}
			}
		}
		emit.done("stop");
	}

	/* ------------------------------------------------------------------
	 * Slide-out chrome
	 * ------------------------------------------------------------------ */
	function buildPanel(iframeSrc) {
		const root = document.createElement("div");
		root.id = "lazychat-dock";
		root.setAttribute("data-lazychat", "1");

		const fab = document.createElement("button");
		fab.id = "lazychat-fab";
		fab.title = "Open assistant";
		fab.innerHTML = '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>';

		const panel = document.createElement("div");
		panel.id = "lazychat-panel";

		const header = document.createElement("div");
		header.id = "lazychat-header";

		const title = document.createElement("div");
		title.id = "lazychat-title";
		title.textContent = "Assistant";

		const closeBtn = document.createElement("button");
		closeBtn.id = "lazychat-close";
		closeBtn.title = "Close";
		closeBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>';

		header.appendChild(title);
		header.appendChild(closeBtn);

		const handle = document.createElement("div");
		handle.id = "lazychat-resize-handle";

		const iframe = document.createElement("iframe");
		iframe.id = "lazychat-iframe";
		iframe.src = iframeSrc;
		iframe.allow = "clipboard-read; clipboard-write";

		panel.appendChild(handle);
		panel.appendChild(header);
		panel.appendChild(iframe);

		root.appendChild(fab);
		root.appendChild(panel);
		document.body.appendChild(root);

		/* Width drag */
		let startX = 0, startW = 0, dragging = false;
		const savedW = parseInt(localStorage.getItem(STORAGE_WIDTH) || "0", 10);
		if (savedW >= WIDTH_MIN) panel.style.width = savedW + "px";
		else panel.style.width = WIDTH_DEFAULT + "px";

		handle.addEventListener("mousedown", (e) => {
			dragging = true;
			startX = e.clientX;
			startW = panel.getBoundingClientRect().width;
			document.body.style.userSelect = "none";
			e.preventDefault();
		});
		window.addEventListener("mousemove", (e) => {
			if (!dragging) return;
			const max = Math.floor(window.innerWidth * WIDTH_MAX_RATIO);
			const w = Math.max(WIDTH_MIN, Math.min(max, startW + (startX - e.clientX)));
			panel.style.width = w + "px";
		});
		window.addEventListener("mouseup", () => {
			if (!dragging) return;
			dragging = false;
			document.body.style.userSelect = "";
			localStorage.setItem(STORAGE_WIDTH, String(panel.getBoundingClientRect().width));
		});

		/* Open/close */
		const isOpen = () => root.classList.contains("lazychat-open");
		const open = () => {
			root.classList.add("lazychat-open");
			localStorage.setItem(STORAGE_OPEN, "1");
		};
		const close = () => {
			root.classList.remove("lazychat-open");
			localStorage.setItem(STORAGE_OPEN, "0");
		};
		fab.addEventListener("click", open);
		closeBtn.addEventListener("click", close);
		if (localStorage.getItem(STORAGE_OPEN) === "1") open();

		return { root, panel, iframe, isOpen, open, close };
	}

	/* ------------------------------------------------------------------
	 * Mount
	 * ------------------------------------------------------------------ */
	function mount() {
		if (document.getElementById("lazychat-dock")) return;
		if (typeof window.frappe === "undefined" || !frappe.boot) return;
		if (!isDeskShell()) return;
		const user = deskUser();
		if (!user || user === "Guest") return;
		if (frappe.boot && frappe.boot.lazychat_panel_enabled === false) return;

		const iframeSrc = resolveIframeSrc();
		const iframeOrigin = originOf(iframeSrc);
		const { iframe } = buildPanel(iframeSrc);

		const bridge = makeBridge(iframe, iframeOrigin);

		const sidToConvo = readSidMap();
		const getConvoId = (sid) => sidToConvo[sid] || null;
		const setConvoId = (sid, convoId) => {
			sidToConvo[sid] = convoId;
			writeSidMap(sidToConvo);
		};

		/* Send init when iframe finishes loading */
		const initPayload = {
			theme: (frappe.boot.user && frappe.boot.user.desk_theme === "Dark") ? "dark" : "light",
			mode: "edit-auto",
			effort: "medium",
			frame: "sidebar",
			hostOrigin: window.location.origin,
		};
		iframe.addEventListener("load", () => {
			bridge.send("init", initPayload);
		});

		/* Track active requests for cancel */
		const aborts = new Map();

		bridge.on("ready", () => {
			console.info("[lazychat] iframe ready");
		});

		bridge.on("agentRequest", (payload) => {
			const ctrl = new AbortController();
			aborts.set(payload.requestId, ctrl);
			runAgentTurn(
				{
					sid: payload.sid,
					requestId: payload.requestId,
					model: payload.model,
					messages: payload.messages,
					params: payload.params,
					signal: ctrl.signal,
				},
				{
					chunk: (delta) =>
						bridge.send("agentChunk", { sid: payload.sid, requestId: payload.requestId, delta }),
					done: (finishReason) => {
						aborts.delete(payload.requestId);
						bridge.send("agentDone", {
							sid: payload.sid,
							requestId: payload.requestId,
							finishReason,
						});
					},
					error: (message, retryable) => {
						aborts.delete(payload.requestId);
						bridge.send("agentError", {
							sid: payload.sid,
							requestId: payload.requestId,
							message,
							retryable,
						});
					},
				},
				getConvoId,
				setConvoId,
			);
		});

		bridge.on("agentCancel", (payload) => {
			const ctrl = aborts.get(payload.requestId);
			if (ctrl) {
				ctrl.abort();
				aborts.delete(payload.requestId);
			}
		});

		/* Forward route changes for context-aware answers */
		if (frappe.router && frappe.router.on) {
			frappe.router.on("change", () => {
				bridge.send("setContext", { context: deskRoute() });
			});
		}

		console.info("[lazychat] panel mounted, iframe src:", iframeSrc);
	}

	function ready(fn) {
		if (document.readyState === "loading") {
			document.addEventListener("DOMContentLoaded", fn);
		} else {
			fn();
		}
	}

	function whenFrappeBoot(fn, tries) {
		tries = tries == null ? 50 : tries;
		if (window.frappe && frappe.boot) return fn();
		if (tries <= 0) return;
		setTimeout(() => whenFrappeBoot(fn, tries - 1), 100);
	}

	ready(() => whenFrappeBoot(mount));

	/* Re-mount on Frappe SPA route changes (Desk replaces #body but preserves <body>) */
	if (window.frappe && frappe.router && frappe.router.on) {
		frappe.router.on("change", () => {
			if (!document.getElementById("lazychat-dock")) mount();
		});
	}
})();
