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

	/* ------------------------------------------------------------------
	 * Theme sync — read Frappe's resolved theme + key CSS vars and push
	 * them into the iframe so chat-ui follows Desk's look (light/dark + brand color).
	 * ------------------------------------------------------------------ */
	function frappeThemeMode() {
		const root = document.documentElement;
		const dsRoot = root.dataset && root.dataset.theme;
		const dsBody = document.body && document.body.getAttribute("data-theme");
		const ds = dsRoot || dsBody;
		if (ds === "dark" || ds === "light") return ds;
		const dt = (window.frappe && frappe.boot && frappe.boot.user && frappe.boot.user.desk_theme) || "";
		if (dt === "Dark") return "dark";
		if (dt === "Light") return "light";
		// "Automatic" or unset → follow OS
		return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
	}

	function readFrappeColors() {
		const cs = getComputedStyle(document.documentElement);
		const v = (n) => (cs.getPropertyValue(n) || "").trim();
		return {
			primary: v("--primary-color") || v("--primary") || v("--brand-color"),
			bg: v("--bg-color") || v("--neutral"),
			fg: v("--text-color") || v("--gray-900"),
			border: v("--border-color") || v("--gray-300"),
			muted: v("--text-muted") || v("--gray-600"),
			elevated: v("--card-bg") || v("--fg-color"),
			input: v("--control-bg") || v("--input-bg"),
		};
	}

	function pushTheme(bridge) {
		const mode = frappeThemeMode();
		bridge.send("setTheme", { theme: mode });
		const c = readFrappeColors();
		// Only push the brand/accent token — NOT surface colors (bg/fg/border/etc).
		// Surface tokens are written as inline styles on <html> which override all
		// [data-theme="dark"] CSS rules, locking the surface to Frappe's current theme
		// and preventing the user from toggling dark/light inside the iframe.
		// Surface colors are managed by chat-ui's own CSS theme system instead.
		const tokens = {};
		if (c.primary) tokens["--color-primary"] = c.primary;
		if (Object.keys(tokens).length) {
			bridge.send("setThemeTokens", { tokens: tokens, persist: false });
		}
	}

	function watchThemeChanges(bridge) {
		// Frappe toggles theme by mutating data-theme on <html>. Re-push on every change.
		try {
			const obs = new MutationObserver(() => pushTheme(bridge));
			obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
			if (document.body) {
				obs.observe(document.body, { attributes: true, attributeFilter: ["data-theme"] });
			}
		} catch (_e) { /* MutationObserver always exists in modern browsers, but guard anyway */ }
		// Also follow OS-level change when Desk theme is "Automatic"
		try {
			const mq = window.matchMedia("(prefers-color-scheme: dark)");
			if (mq && mq.addEventListener) {
				mq.addEventListener("change", () => pushTheme(bridge));
			}
		} catch (_e) { /* ignore */ }
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

	function lazychatSettings() {
		// Source of truth: frappe.boot.lazychat_settings (populated by boot.py from
		// the Lazychat Settings doctype + site_config overrides). Falls back to legacy
		// frappe.boot.lazychat_iframe_src for one release cycle.
		const boot = (window.frappe && frappe.boot) || {};
		const settings = boot.lazychat_settings || {};
		const legacyIframeSrc = boot.lazychat_iframe_src || null;
		const baseUrl = settings.iframe_base_url || "/assets/lazychat_mcp_erpnext/lazychat_dist/index.html";
		const queryParams = settings.iframe_query_params || "?frame=sidebar";
		// Cache-bust the iframe URL when the bundled chat-ui changes. Frappe serves the dist
		// with Cache-Control: max-age=43200 (12h), so without this the browser keeps loading
		// the OLD index.html — which references the OLD hashed asset bundle.
		// Prefer settings.deploy_version (boot.py composes "<app_version>.<dist mtime>" — flips
		// on every rebuild). Fall back to the static app version, then empty.
		const cacheBust = (settings.deploy_version
			|| (boot.versions && boot.versions.lazychat_mcp_erpnext)
			|| "");
		const sep = queryParams.includes("?") ? "&" : "?";
		const finalQuery = cacheBust ? queryParams + sep + "v=" + encodeURIComponent(cacheBust) : queryParams;
		return {
			enabled: settings.enabled !== undefined ? !!settings.enabled : (boot.lazychat_panel_enabled !== false),
			legacyWidget: !!(settings.legacy_widget_enabled || boot.lazychat_legacy_widget_enabled),
			chatPath: settings.chat_path || "auto",
			mcpEndpoint: settings.mcp_endpoint || "/api/method/lazychat_mcp_erpnext.desk_assistant.mcp.handle",
			iframeSrc: legacyIframeSrc || (baseUrl + finalQuery),
		};
	}

	function resolveIframeSrc() {
		return lazychatSettings().iframeSrc;
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

	/* ------------------------------------------------------------------
	 * Tier B-upload — /upload TOKEN slash command. Opens a native file picker,
	 * uploads to /api/method/upload_file, then commits the staged attach_file
	 * action with the new file_url. Skips the LLM entirely (same pattern as
	 * /commit). User aborts the picker → no-op, prompt them to pick again.
	 * ------------------------------------------------------------------ */
	function runUploadCommand(token, emit) {
		emit.chunk("Opening file picker for token `" + token + "` …\n\n");
		const input = document.createElement("input");
		input.type = "file";
		// `accept` from the staged token would require a server roundtrip just
		// for the filter; v1 accepts everything and lets the user pick. The
		// agent surfaces the accept hint in its narration so the user knows
		// what to pick.
		input.style.display = "none";
		document.body.appendChild(input);
		input.addEventListener("change", function () {
			const file = input.files && input.files[0];
			document.body.removeChild(input);
			if (!file) {
				emit.chunk("_No file selected — aborted._");
				emit.done("stop");
				return;
			}
			emit.chunk("Uploading " + file.name + " (" + Math.round(file.size / 1024) + " KB) …\n\n");
			const fd = new FormData();
			fd.append("file", file);
			fd.append("is_private", "1");
			fd.append("optimize", "0");
			fetch("/api/method/upload_file", {
				method: "POST",
				credentials: "include",
				headers: { "X-Frappe-CSRF-Token": csrf() },
				body: fd,
			})
				.then(function (r) { return r.json(); })
				.then(function (j) {
					const uploaded = (j && j.message) || {};
					const fileUrl = uploaded.file_url;
					if (!fileUrl) {
						throw new Error("upload_file returned no file_url: " + JSON.stringify(uploaded));
					}
					emit.chunk("Uploaded → " + fileUrl + ". Attaching …\n\n");
					return fetch("/api/method/lazychat_mcp_erpnext.desk_assistant.api.commit_prepared_action", {
						method: "POST",
						credentials: "include",
						headers: {
							"Content-Type": "application/json",
							"X-Frappe-CSRF-Token": csrf(),
						},
						body: JSON.stringify({ token: token, file_url: fileUrl }),
					});
				})
				.then(function (r) { return r.json(); })
				.then(function (j) {
					const m = (j && j.message) || {};
					if (m.ok) {
						const link = m.link ? "[" + m.doctype + "/" + m.name + "](" + m.link + ")" : (m.doctype + "/" + m.name);
						emit.chunk("**Attached** — file linked to " + link + "\n");
					} else {
						emit.chunk("**Failed** — " + (m.error || "Unknown error") + "\n");
					}
					emit.done("stop");
				})
				.catch(function (err) { emit.error(String(err && err.message ? err.message : err), true); });
		}, { once: true });
		// Trigger the OS picker
		input.click();
	}

	function runAgentTurn(req, emit, getConvoId, setConvoId) {
		const userText = lastUserText(req.messages);
		const commitMatch = /^\s*\/commit\s+(\S+)\s*$/.exec(userText);
		if (commitMatch) {
			runCommitCommand(commitMatch[1], emit);
			return;
		}
		const uploadMatch = /^\s*\/upload\s+(\S+)\s*$/.exec(userText);
		if (uploadMatch) {
			runUploadCommand(uploadMatch[1], emit);
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

		const handle = document.createElement("div");
		handle.id = "lazychat-resize-handle";

		const iframe = document.createElement("iframe");
		iframe.id = "lazychat-iframe";
		iframe.src = iframeSrc;
		iframe.allow = "clipboard-read; clipboard-write";

		panel.appendChild(handle);
		panel.appendChild(iframe);

		root.appendChild(fab);
		root.appendChild(panel);
		document.body.appendChild(root);

		/* Width drag — rAF-coalesced; iframe pointer-events disabled during drag so
		 * mousemove keeps reaching the parent window once the cursor enters the iframe. */
		let startX = 0, startW = 0, dragging = false, pendingW = 0, rafId = 0;
		const savedW = parseInt(localStorage.getItem(STORAGE_WIDTH) || "0", 10);
		if (savedW >= WIDTH_MIN) panel.style.width = savedW + "px";
		else panel.style.width = WIDTH_DEFAULT + "px";

		const applyPending = () => {
			rafId = 0;
			panel.style.width = pendingW + "px";
		};

		handle.addEventListener("mousedown", (e) => {
			dragging = true;
			startX = e.clientX;
			startW = panel.getBoundingClientRect().width;
			pendingW = startW;
			document.body.classList.add("lazychat-resizing");
			e.preventDefault();
		});
		window.addEventListener("mousemove", (e) => {
			if (!dragging) return;
			const max = Math.floor(window.innerWidth * WIDTH_MAX_RATIO);
			pendingW = Math.max(WIDTH_MIN, Math.min(max, startW + (startX - e.clientX)));
			if (!rafId) rafId = requestAnimationFrame(applyPending);
		}, { passive: true });
		const endDrag = () => {
			if (!dragging) return;
			dragging = false;
			if (rafId) { cancelAnimationFrame(rafId); rafId = 0; }
			panel.style.width = pendingW + "px";
			document.body.classList.remove("lazychat-resizing");
			localStorage.setItem(STORAGE_WIDTH, String(pendingW));
		};
		window.addEventListener("mouseup", endDrag);
		window.addEventListener("mouseleave", endDrag);
		window.addEventListener("blur", endDrag);

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

		const settings = lazychatSettings();
		// Master kill-switch (doctype: enabled, with backward-compat to boot.lazychat_panel_enabled)
		if (!settings.enabled) return;
		// Mutually exclusive with the legacy widget — when admin flips legacy on, we step aside
		// so the old vanilla-JS panel can mount (its own gate at claude_assistant_desk.js:60-63
		// reads frappe.boot.lazychat_legacy_widget_enabled).
		if (settings.legacyWidget) return;

		const iframeSrc = settings.iframeSrc;
		const iframeOrigin = originOf(iframeSrc);
		const { panel, iframe, close } = buildPanel(iframeSrc);

		const bridge = makeBridge(iframe, iframeOrigin);

		/* The iframe (chat-ui SidebarChrome) emits `closed` when the user clicks
		 * its own X button. Forward that to the outer panel so we don't need a
		 * second close button in our header. */
		bridge.on("closed", () => close());

		/* Maximize toggle: chat-ui emits maximizeChanged when the user clicks the
		 * Maximize2 icon in SidebarChrome. We stretch #lazychat-panel to full
		 * viewport width via a CSS class; the class also hides the resize handle.
		 * Restoring drops back to the saved width set by the drag handle. */
		bridge.on("maximizeChanged", (payload) => {
			panel.classList.toggle("lazychat-maximized", !!(payload && payload.maximized));
		});

		const sidToConvo = readSidMap();
		const getConvoId = (sid) => sidToConvo[sid] || null;
		const setConvoId = (sid, convoId) => {
			sidToConvo[sid] = convoId;
			writeSidMap(sidToConvo);
		};

		/* Send init when iframe finishes loading. Includes new browser-LLM-path config:
		 *   chatPath, mcpEndpoint, mcpAuth, saveEndpoint
		 * chat-ui ignores unknown init keys, so this is harmless even when the bundled
		 * dist hasn't been rebuilt with Phase B (mcp-client.ts) yet. */
		const csrf = (window.frappe && window.frappe.csrf_token) || "";
		// Resolve to absolute URL so the iframe can reach Frappe even when it's loaded
		// cross-origin (HMR dev: iframe @ localhost:5173, Frappe @ localhost:8000).
		// In production the iframe is same-origin, so this is a no-op transformation.
		const _abs = (p) => {
			if (!p) return p;
			if (/^https?:\/\//i.test(p)) return p;
			return window.location.origin + (p.startsWith("/") ? p : "/" + p);
		};
		const initPayload = {
			theme: (frappe.boot.user && frappe.boot.user.desk_theme === "Dark") ? "dark" : "light",
			mode: "edit-auto",
			effort: "medium",
			frame: "sidebar",
			hostOrigin: window.location.origin,
			chatPath: settings.chatPath,
			mcpEndpoint: _abs(settings.mcpEndpoint),
			mcpAuth: { csrf: csrf },
			saveEndpoint: _abs("/api/method/lazychat_mcp_erpnext.desk_assistant.api.save_conversation"),
			// Server-side LLM proxy for cross-origin custom-model calls (NVIDIA, OpenAI, etc).
			// chat-ui's resolveFetchTarget routes here instead of the dev-only /llm-proxy.
			llmProxyUrl: _abs("/api/method/lazychat_mcp_erpnext.desk_assistant.llm_proxy.handle"),
		};
		iframe.addEventListener("load", () => {
			bridge.send("init", initPayload);
		});

		/* Track active requests for cancel */
		const aborts = new Map();

		bridge.on("ready", () => {
			console.info("[lazychat] iframe ready");
			// Push current Frappe theme + accent color, then keep them in sync.
			pushTheme(bridge);
			watchThemeChanges(bridge);
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

		/* Tier A — agent emits markdown links like [SO26001040](/app/sales-order/SO26001040);
		 * the chat-ui intercepts the click and sends `navigateDesk { route, openInNewTab? }`.
		 * For /app/<doctype>/<name?> we navigate the Desk via frappe.set_route — this is
		 * a SPA route change, doesn't reload, preserves the lazychat panel state.
		 * For /files/* (attachments) we always open in a new tab so the user keeps the chat. */
		bridge.on("navigateDesk", (payload) => {
			const route = payload && payload.route;
			if (!route || typeof route !== "string") return;
			if (payload.openInNewTab) {
				window.open(route, "_blank");
				return;
			}
			const appMatch = route.match(/^\/app\/([^\/?#]+)(?:\/([^?#]+))?/);
			if (appMatch && window.frappe && frappe.set_route) {
				const doctype = appMatch[1];
				const name = appMatch[2] ? decodeURIComponent(appMatch[2]) : undefined;
				try {
					if (name) frappe.set_route(doctype, name); else frappe.set_route(doctype);
					return;
				} catch (e) {
					console.warn("[lazychat] frappe.set_route failed, falling back to location.assign", e);
				}
			}
			// Files, or /app/ without router available: fall back to navigation.
			if (/^\/(?:files|private\/files)\//.test(route)) {
				window.open(route, "_blank");
			} else {
				window.location.assign(route);
			}
		});

		/* Tier D — subscribe to lazychat_doc_update events on Frappe's realtime
		 * channel (Socket.IO) and forward them to the iframe as realtimeEvent
		 * envelopes. The backend's universal on_update hook publishes to
		 * frappe.realtime; we just relay. Per-user filtering already happened
		 * server-side, so every event we receive is FOR this user. */
		if (window.frappe && frappe.realtime && typeof frappe.realtime.on === "function") {
			frappe.realtime.on("lazychat_doc_update", function (data) {
				try {
					bridge.send("realtimeEvent", {
						kind: "doc_update",
						doctype: (data && data.doctype) || "",
						name: (data && data.name) || "",
						action: (data && data.action) || "update",
						modified_by: (data && data.modified_by) || null,
						workflow_state: (data && data.workflow_state) || null,
						status: (data && data.status) || null,
						docstatus: (data && data.docstatus) || null,
						link: (data && data.link) || null,
					});
				} catch (e) {
					console.warn("[lazychat] realtime relay failed", e);
				}
			});
		}

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
