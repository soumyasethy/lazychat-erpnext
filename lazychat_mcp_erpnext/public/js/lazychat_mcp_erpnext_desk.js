/**
 * ERPNext / Frappe desk — right-docked AI assistant (multi-provider).
 * Loaded via hooks app_include_js (?v= app version).
 * After changing this file or desk CSS: bench build --app lazychat_mcp_erpnext && bench --site <site> clear-cache
 */
(function () {
	"use strict";

	if (typeof console !== "undefined" && console.info) {
		console.info("[lazychat_mcp_erpnext] desk script loaded");
	}

	const STORAGE_MODEL = "lazychat_mcp_erpnext_model";
	const STORAGE_OPEN = "lazychat_mcp_erpnext_panel_open";
	const STORAGE_WIDTH = "lazychat_mcp_erpnext_panel_width";
	const WIDTH_MIN = 280;
	const WIDTH_MAX_RATIO = 0.92;
	const OPT_ADD_CUSTOM_MODEL = "__add_custom_model__";

	function escapeHtml(s) {
		const d = document.createElement("div");
		d.textContent = s == null ? "" : String(s);
		return d.innerHTML;
	}

	function deskUser() {
		if (frappe.session && frappe.session.user) return frappe.session.user;
		if (frappe.boot && frappe.boot.user && frappe.boot.user.name) return frappe.boot.user.name;
		return null;
	}

	function deskContext() {
		const r = (frappe.get_route && frappe.get_route()) || [];
		return {
			route: r,
			user: deskUser(),
			doctype: r[0] === "Form" ? r[1] : null,
			docname: r[0] === "Form" ? r[2] : null,
		};
	}

	function isDeskShell() {
		/* app.html sets window.app — pathname check is fallback only */
		if (window.app === true) return true;
		const p = window.location.pathname || "";
		return p === "/app" || p.startsWith("/app/");
	}

	function dbgSkip(reason) {
		try {
			if (frappe.boot && frappe.boot.developer_mode) {
				console.warn("[lazychat_mcp_erpnext] mount skipped:", reason);
			}
		} catch (e) {
			/* ignore */
		}
	}

	function tryMountDeskAssistant() {
		if (window.frappe && frappe.boot && frappe.boot.lazychat_legacy_widget_enabled === false) {
			dbgSkip("legacy widget disabled (lazychat_legacy_widget_enabled=false)");
			return;
		}
		const existingDock = document.getElementById("claude-assistant-dock");
		if (existingDock) {
			if (existingDock.getAttribute("data-cad-layout") === "v3") return;
			existingDock.remove();
		}
		if (typeof window.frappe === "undefined" || !frappe.boot) {
			dbgSkip("no frappe.boot yet");
			return;
		}
		if (!isDeskShell()) {
			dbgSkip("not desk shell");
			return;
		}
		const user = deskUser();
		if (!user || user === "Guest") {
			dbgSkip("no desk user or Guest");
			return;
		}

		const host = document.createElement("div");
		host.id = "claude-assistant-dock";
		host.setAttribute("data-claude-assistant-desk", "1");
		host.setAttribute("data-cad-layout", "v3");

		const ic = {
			plus:
				'<svg class="cad-svg" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 5v14M5 12h14"/></svg>',
			clock:
				'<svg class="cad-svg" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="8.5" fill="none" stroke="currentColor" stroke-width="2"/><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 8v4l3 2"/></svg>',
			dots:
				'<svg class="cad-svg" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="6" r="1.75" fill="currentColor"/><circle cx="12" cy="12" r="1.75" fill="currentColor"/><circle cx="12" cy="18" r="1.75" fill="currentColor"/></svg>',
			dock:
				'<svg class="cad-svg" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" d="M9 5h10v14H9zM5 5h3v14H5z"/></svg>',
			minimize:
				'<svg class="cad-svg cad-svg--msgs-min" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="5" y="5" width="14" height="11" rx="2" fill="none" stroke="currentColor" stroke-width="1.75"/><path fill="none" stroke="currentColor" stroke-width="2.25" stroke-linecap="round" d="M7 18h10"/></svg>',
			close:
				'<svg class="cad-svg" width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M6 6l12 12M18 6L6 18"/></svg>',
			spark:
				'<svg class="cad-svg cad-svg--sm" width="14" height="14" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M11 21l1-7H6l9-13v13h5l-9 7z"/></svg>',
			sendUp:
				'<svg class="cad-svg" width="18" height="18" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="M12 19V5M5 12l7-7 7 7"/></svg>',
			/* Image attach — outline mountain + sun (Cursor-style composer) */
			image:
				'<svg class="cad-svg" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><rect x="3" y="5" width="18" height="14" rx="2" ry="2" fill="none" stroke="currentColor" stroke-width="1.75"/><circle cx="9" cy="9" r="1.25" fill="currentColor"/><path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14"/></svg>',
			chev:
				'<svg class="cad-chevron-svg" width="10" height="10" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M7 10l5 5 5-5H7z"/></svg>',
			/* Key — empty composer setup (SVG per ui-ux-pro-max, not emoji) */
			key:
				'<svg class="cad-svg" width="22" height="22" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="8" cy="15" r="4" fill="none" stroke="currentColor" stroke-width="1.75"/><path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" d="M11 12l9-9"/><path fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" d="M17 6l4 4"/></svg>',
		};

		host.innerHTML =
			'<div class="cad-wrap">' +
			'<div class="cad-resize" data-cad="resize" title="Drag to resize width" role="separator" aria-orientation="vertical" aria-label="Resize assistant width"></div>' +
			'<button class="cad-tab" type="button" data-cad="tab" title="Open assistant panel"><span class="cad-tab-inner">Ask</span></button>' +
			'<section class="cad-panel" data-cad="panel" role="region" aria-labelledby="cad-heading">' +
			'<header class="cad-topbar">' +
			'<div class="cad-tabs">' +
			'<div class="cad-tab-pill">' +
			'<span id="cad-heading" class="cad-tab-title">Desk assistant</span>' +
			'<button type="button" class="cad-tab-close" data-cad="close" title="Collapse panel" aria-label="Collapse assistant panel">' +
			ic.close +
			"</button>" +
			"</div>" +
			"</div>" +
			'<div class="cad-top-actions">' +
			'<button type="button" class="cad-icon-btn" data-cad="new-chat" title="New chat" aria-label="New chat">' +
			ic.plus +
			"</button>" +
			'<button type="button" class="cad-icon-btn" data-cad="history" title="History" aria-label="Scroll to history">' +
			ic.clock +
			"</button>" +
			'<button type="button" class="cad-icon-btn" data-cad="menu" title="More" aria-label="More actions">' +
			ic.dots +
			"</button>" +
			'<button type="button" class="cad-icon-btn" data-cad="collapse" title="Collapse panel width" aria-label="Minimize assistant">' +
			ic.dock +
			"</button>" +
			"</div>" +
			"</header>" +
			'<div class="cad-msgs-region">' +
			'<button type="button" class="cad-msgs-min-btn cad-msgs-min--float" data-cad="msgs-minimize" title="Minimize assistant" aria-label="Minimize assistant">' +
			ic.minimize +
			"</button>" +
			'<div class="cad-msgs" data-cad="msgs" role="log" aria-relevant="additions"></div>' +
			"</div>" +
			'<footer class="cad-composer" data-cad="composer-footer" role="region" aria-labelledby="cad-composer-field-label">' +
			'<label id="cad-composer-field-label" class="visually-hidden" for="cad-claude-float-ta">Message</label>' +
			'<p id="cad-composer-status" class="cad-composer-status" data-cad="composer-status" role="status" aria-live="polite"></p>' +
			'<select class="cad-model-picker cad-model-picker--hidden" data-cad="model-picker" aria-label="AI model" tabindex="-1">' +
			"<option>Loading…</option>" +
			"</select>" +
			'<input type="file" class="cad-composer-file-input" data-cad="file-input" multiple tabindex="-1" accept="image/*,.csv,.txt,text/csv,text/plain" />' +
			"</footer>" +
			"</section>" +
			"</div>";

		document.body.appendChild(host);

		const $ = (sel) => host.querySelector(sel);
		const wrap = host.querySelector(".cad-wrap");
		const panel = $('[data-cad="panel"]');
		const tab = $('[data-cad="tab"]');
		const msgs = $('[data-cad="msgs"]');
		const modelPicker = $('[data-cad="model-picker"]');
		const resizeEl = $('[data-cad="resize"]');
		const fileInput = $('[data-cad="file-input"]');
		const composerFooter = $('[data-cad="composer-footer"]');
		const composerStatusEl = $('[data-cad="composer-status"]');
		const headingEl = document.getElementById("cad-heading");

		initCadDevShell();

		const inp = host.querySelector('[data-cad="inp"]');
		const sendBtn = host.querySelector('[data-cad-float="float-send"]');
		const attachmentListEl = host.querySelector('[data-cad="attachment-list"]');

		if (!wrap || !panel || !tab || !msgs || !modelPicker || !fileInput || !composerFooter || !inp || !sendBtn) {
			console.error("[lazychat_mcp_erpnext] dock template nodes missing");
			host.remove();
			return;
		}

		/** Last model count from API — drives footer setup slab visibility */
		let modelListCount = 0;
		/** True until first list_models completes (send stays disabled). */
		let modelListLoading = true;
		let modelListLoadFailed = false;
		/** While send() awaits API — keeps Send disabled even when a model is selected. */
		let composerSendInFlight = false;

		/**
		 * Thread welcome handles onboarding; footer no longer shows duplicate GPT composer slab.
		 */
		function syncComposerSetupBanner() {
			/* no-op */
		}

		function hasSendableModel() {
			if (modelListLoading) return false;
			if (modelListLoadFailed) return false;
			if (!modelListCount) return false;
			const v = modelPicker.value;
			if (!v || v === OPT_ADD_CUSTOM_MODEL) return false;
			const opt = modelPicker.selectedOptions[0];
			if (opt && opt.disabled) return false;
			return true;
		}

		function syncComposerFooterState() {
			if (!sendBtn) return;
			if (composerStatusEl && composerFooter) {
				let msg = "";
				let show = false;
				if (modelListLoading) {
					msg = "Loading models…";
					show = true;
				} else if (modelListLoadFailed) {
					msg = "Could not load models. Open LLM Provider and try again.";
					show = true;
				} else if (!modelListCount) {
					msg =
						"No model yet. Add an API key in LLM Provider, then choose a model—or use Add custom model.";
					show = true;
				}
				if (show && msg) {
					composerStatusEl.textContent = msg;
					composerFooter.setAttribute("aria-describedby", "cad-composer-status");
				} else {
					composerStatusEl.textContent = "";
					composerFooter.removeAttribute("aria-describedby");
				}
			}
			sendBtn.disabled = composerSendInFlight || !hasSendableModel();
			if (modelPicker) {
				modelPicker.setAttribute(
					"aria-label",
					hasSendableModel() ? "AI model" : "AI model — pick one to enable Send"
				);
			}
			const floatSendBtn = document.querySelector("[data-cad-float=\"float-send\"]");
			if (floatSendBtn && sendBtn) floatSendBtn.disabled = sendBtn.disabled;
		}

		const MAX_ATTACHMENT_BYTES = 2 * 1024 * 1024;
		const MAX_ATTACHMENTS = 8;
		/** @type {{ name: string, media_type: string, data: string }[]} */
		let pendingAttachments = [];

		function renderAttachmentStrip() {
			if (!attachmentListEl) return;
			if (!pendingAttachments.length) {
				attachmentListEl.innerHTML = "";
				attachmentListEl.hidden = true;
				return;
			}
			attachmentListEl.hidden = false;
			attachmentListEl.innerHTML = pendingAttachments
				.map(function (a, i) {
					const safeName = escapeHtml(a.name || "file");
					return (
						'<span class="cad-attach-chip" role="listitem">' +
						'<span class="cad-attach-chip-name" title="' +
						safeName +
						'">' +
						safeName +
						"</span>" +
						'<button type="button" class="cad-attach-chip-remove" data-cad-attach-idx="' +
						i +
						'" title="Remove attachment" aria-label="Remove attachment">' +
						"&times;" +
						"</button>" +
						"</span>"
					);
				})
				.join("");
		}

		function inferMediaType(file) {
			let media = file.type || "";
			if (media) return media;
			const n = file.name || "";
			if (/\.csv$/i.test(n)) return "text/csv";
			if (/\.txt$/i.test(n)) return "text/plain";
			const im = /\.(png|jpe?g|gif|webp)$/i.exec(n);
			if (im) {
				const ext = im[1].toLowerCase();
				if (ext === "jpg" || ext === "jpeg") return "image/jpeg";
				if (ext === "png") return "image/png";
				if (ext === "gif") return "image/gif";
				if (ext === "webp") return "image/webp";
			}
			return "application/octet-stream";
		}

		function fileToAttachment(file) {
			return new Promise(function (resolve, reject) {
				if (file.size > MAX_ATTACHMENT_BYTES) {
					reject(new Error("File too large (max 2 MB): " + file.name));
					return;
				}
				const reader = new FileReader();
				reader.onload = function () {
					const s = reader.result;
					const comma = typeof s === "string" ? s.indexOf(",") : -1;
					const b64 = comma >= 0 ? s.slice(comma + 1) : String(s);
					resolve({
						name: file.name || "attachment",
						media_type: inferMediaType(file),
						data: b64,
					});
				};
				reader.onerror = function () {
					reject(new Error("Could not read file"));
				};
				reader.readAsDataURL(file);
			});
		}

		async function addFilesFromInput(fileList) {
			if (!fileList || !fileList.length) return;
			const arr = Array.from(fileList);
			const room = MAX_ATTACHMENTS - pendingAttachments.length;
			if (room <= 0) {
				if (typeof frappe !== "undefined" && frappe.show_alert) {
					frappe.show_alert({
						message: "Maximum " + MAX_ATTACHMENTS + " attachments.",
						indicator: "orange",
					});
				}
				return;
			}
			const take = arr.slice(0, room);
			for (const file of take) {
				try {
					pendingAttachments.push(await fileToAttachment(file));
				} catch (e) {
					if (typeof frappe !== "undefined" && frappe.show_alert) {
						frappe.show_alert({
							message: (e && e.message) || String(e),
							indicator: "red",
						});
					}
				}
			}
			renderAttachmentStrip();
		}

		if (attachmentListEl) {
			attachmentListEl.addEventListener("click", function (ev) {
				const btn = ev.target && ev.target.closest("button[data-cad-attach-idx]");
				if (!btn || !attachmentListEl.contains(btn)) return;
				ev.preventDefault();
				const idx = parseInt(btn.getAttribute("data-cad-attach-idx"), 10);
				if (Number.isNaN(idx)) return;
				pendingAttachments.splice(idx, 1);
				renderAttachmentStrip();
			});
		}

		if (fileInput) {
			fileInput.addEventListener("change", function () {
				addFilesFromInput(fileInput.files).finally(function () {
					fileInput.value = "";
				});
			});
		}

		function goList(doctype) {
			if (typeof frappe !== "undefined" && frappe.set_route) {
				frappe.set_route("List", doctype);
			}
		}

		function clampWidth(px) {
			const maxW = Math.floor(window.innerWidth * WIDTH_MAX_RATIO);
			let n = parseInt(px, 10);
			if (Number.isNaN(n)) n = 420;
			return Math.min(Math.max(n, WIDTH_MIN), maxW);
		}

		function readStoredWidth() {
			return clampWidth(localStorage.getItem(STORAGE_WIDTH) || "420");
		}

		function applyPanelWidth(px) {
			const w = clampWidth(px);
			localStorage.setItem(STORAGE_WIDTH, String(w));
			document.documentElement.style.setProperty("--cad-panel-width", w + "px");
		}

		let open = localStorage.getItem(STORAGE_OPEN) !== "0";
		let conversationId = null;
		let selectedModel = localStorage.getItem(STORAGE_MODEL) || null;

		function syncLayoutShift() {
			/* Reserve horizontal space on the desk only when the chat column is expanded */
			if (open) {
				document.body.classList.add("cad-dock-shift");
				applyPanelWidth(readStoredWidth());
			} else {
				document.body.classList.remove("cad-dock-shift");
			}
			wrap.classList.toggle("cad-narrow", !open);
		}

		function setOpen(v) {
			open = v;
			localStorage.setItem(STORAGE_OPEN, v ? "1" : "0");
			syncLayoutShift();
		}

		applyPanelWidth(readStoredWidth());
		syncLayoutShift();

		let resizeActive = false;
		let resizeStartX = 0;
		let resizeStartW = 0;
		function endResize() {
			if (!resizeActive) return;
			resizeActive = false;
			document.body.style.cursor = "";
			document.body.style.userSelect = "";
		}
		if (resizeEl) {
			resizeEl.addEventListener("mousedown", function (ev) {
				if (!open) return;
				ev.preventDefault();
				resizeActive = true;
				resizeStartX = ev.clientX;
				resizeStartW = readStoredWidth();
				document.body.style.cursor = "col-resize";
				document.body.style.userSelect = "none";
			});
		}
		document.addEventListener("mousemove", function (ev) {
			if (!resizeActive) return;
			const delta = resizeStartX - ev.clientX;
			applyPanelWidth(resizeStartW + delta);
		});
		window.addEventListener("mouseup", endResize);
		window.addEventListener("blur", endResize);

		window.addEventListener(
			"resize",
			function () {
				if (open) applyPanelWidth(readStoredWidth());
			},
			{ passive: true }
		);

		tab.addEventListener("click", () => setOpen(!open));
		$('[data-cad="close"]').addEventListener("click", () => setOpen(false));
		const collapseBtn = $('[data-cad="collapse"]');
		if (collapseBtn) collapseBtn.addEventListener("click", () => setOpen(false));
		const msgsMinBtn = $('[data-cad="msgs-minimize"]');
		if (msgsMinBtn) msgsMinBtn.addEventListener("click", () => setOpen(false));
		const newChatBtn = $('[data-cad="new-chat"]');
		if (newChatBtn) {
			newChatBtn.addEventListener("click", function () {
				conversationId = null;
				pendingAttachments = [];
				renderAttachmentStrip();
				renderWelcome();
			});
		}

		function renderCtx() {
			if (!headingEl) return;
			const c = deskContext();
			const bits = [];
			if (c.doctype) bits.push(c.doctype);
			if (c.docname) bits.push(c.docname);
			const label = bits.length ? bits.join(" · ") : "Desk assistant";
			headingEl.textContent = label;
			headingEl.title = bits.length ? label : "";
		}
		renderCtx();

		const historyBtn = $('[data-cad="history"]');
		if (historyBtn) {
			historyBtn.addEventListener("click", function () {
				msgs.scrollTop = 0;
			});
		}

		function appendBubble(role, html) {
			const d = document.createElement("div");
			d.className = "cad-bubble cad-" + role;
			d.innerHTML = html;
			msgs.appendChild(d);
			msgs.scrollTop = msgs.scrollHeight;
			return d;
		}

		function renderWelcome() {
			msgs.innerHTML = "";
			const el = document.createElement("div");
			el.className = "cad-empty cad-empty--figma cad-empty--gpt-thread";
			el.setAttribute("role", "region");
			el.setAttribute("aria-labelledby", "cad-welcome-title");
			el.innerHTML =
				'<div class="cad-empty-gpt-hero">' +
				'<h1 class="cad-empty-gpt-headline" id="cad-welcome-title">What are you working on?</h1>' +
				"</div>" +
				'<div class="cad-empty-slab cad-empty-slab--lilac">' +
				'<header class="cad-empty-header">' +
				'<p class="cad-empty-eyebrow">Quick start</p>' +
				'<h2 class="cad-empty-title">Connect your AI backend</h2>' +
				"</header>" +
				'<p class="cad-empty-body">Add your API key and pick a model in <strong>LLM Provider</strong> / <strong>LLM Model</strong>, then type below.</p>' +
				'<div class="cad-empty-actions">' +
				'<button type="button" class="cad-btn cad-btn--figma-primary" data-cad="open-llm-provider">Open LLM Provider</button>' +
				'<button type="button" class="cad-btn cad-btn--figma-outline" data-cad="open-llm-model">Browse models</button>' +
				"</div>" +
				'<section class="cad-empty-checklist" aria-labelledby="cad-welcome-steps-label">' +
				'<p class="cad-empty-checklist-kicker" id="cad-welcome-steps-label">Next steps</p>' +
				'<ol class="cad-empty-steps">' +
				"<li><span class=\"cad-empty-step-num\" aria-hidden=\"true\">1</span><span>Provider &amp; API key</span></li>" +
				"<li><span class=\"cad-empty-step-num\" aria-hidden=\"true\">2</span><span>Pick a model</span></li>" +
				"<li><span class=\"cad-empty-step-num\" aria-hidden=\"true\">3</span><span>Send a message</span></li>" +
				"</ol>" +
				"</section>" +
				"</div>";
			msgs.appendChild(el);
			el.querySelector('[data-cad="open-llm-provider"]').addEventListener("click", function () {
				goList("LLM Provider");
			});
			el.querySelector('[data-cad="open-llm-model"]').addEventListener("click", function () {
				goList("LLM Model");
			});
			msgs.scrollTop = 0;
			syncComposerSetupBanner();
		}

		function appendTool(summary, detail) {
			const d = document.createElement("div");
			d.className = "cad-bubble cad-tool";
			d.innerHTML =
				"<strong>" +
				escapeHtml(summary) +
				"</strong>" +
				(detail ? "<pre class='cad-raw'>" + escapeHtml(detail) + "</pre>" : "");
			msgs.appendChild(d);
			msgs.scrollTop = msgs.scrollHeight;
		}

		function pickFirstModelValue() {
			const opts = Array.from(modelPicker.options);
			for (let i = 0; i < opts.length; i++) {
				const v = opts[i].value;
				if (v && v !== OPT_ADD_CUSTOM_MODEL && !opts[i].disabled) return v;
			}
			return "";
		}

		function syncModelPickerSelection(models) {
			if (!models || !models.length) {
				selectedModel = "";
				return;
			}
			if (selectedModel && models.some((m) => m.model_label === selectedModel)) {
				modelPicker.value = selectedModel;
				return;
			}
			const def = models.find((m) => m.is_default);
			selectedModel = def ? def.model_label : models[0].model_label;
			modelPicker.value = selectedModel;
			localStorage.setItem(STORAGE_MODEL, selectedModel);
		}

		async function loadModels() {
			modelListLoading = true;
			modelListLoadFailed = false;
			if (modelPicker) modelPicker.disabled = true;
			syncComposerFooterState();
			try {
				const r = await frappe.call({ method: "lazychat_mcp_erpnext.desk_assistant.api.list_models" });
				const models = r.message || [];
				modelListCount = models.length;
				modelListLoadFailed = false;
				const rows = [];
				const floatDock = document.getElementById("cad-claude-float-layer");
				if (floatDock) floatDock.classList.toggle("cad-claude-float-layer--needs-setup", !models.length);
				if (models.length) {
					const welcomeEl = msgs.querySelector(".cad-empty");
					if (welcomeEl) welcomeEl.remove();
				}
				if (!models.length) {
					inp.placeholder = "Add a provider key first…";
					rows.push("<option value=\"\" disabled selected>No model yet</option>");
				} else {
					inp.placeholder = "Add a follow-up";
					models.forEach((m) => {
						const sel =
							(selectedModel === m.model_label) || (!selectedModel && m.is_default)
								? " selected"
								: "";
						const suf = m.supports_tools ? " · tools" : "";
						rows.push(
							"<option value=\"" +
								escapeHtml(m.model_label) +
								"\"" +
								sel +
								">" +
								escapeHtml(m.model_label) +
								suf +
								"</option>"
						);
					});
				}
				rows.push(
					"<option value=\"" +
						OPT_ADD_CUSTOM_MODEL +
						"\">Add custom model…</option>"
				);
				modelPicker.innerHTML = rows.join("");
				if (models.length) syncModelPickerSelection(models);
				else selectedModel = "";
				syncComposerSetupBanner();
			} catch (e) {
				modelListCount = 0;
				modelListLoadFailed = true;
				const floatDock = document.getElementById("cad-claude-float-layer");
				if (floatDock) floatDock.classList.add("cad-claude-float-layer--needs-setup");
				inp.placeholder = "Add a provider key first…";
				modelPicker.innerHTML =
					"<option value=\"\" disabled selected>Could not load models</option>" +
					"<option value=\"" +
					OPT_ADD_CUSTOM_MODEL +
					"\">Add custom model…</option>";
				syncComposerSetupBanner();
			} finally {
				modelListLoading = false;
				if (modelPicker) modelPicker.disabled = false;
				syncComposerFooterState();
				if (typeof window.__cad_on_models_loaded === "function") {
					try {
						window.__cad_on_models_loaded();
					} catch (e2) {
						/* ignore */
					}
				}
			}
		}

		modelPicker.addEventListener("change", function () {
			const v = modelPicker.value;
			if (v === OPT_ADD_CUSTOM_MODEL) {
				const fallback = pickFirstModelValue();
				if (selectedModel && Array.from(modelPicker.options).some((o) => o.value === selectedModel)) {
					modelPicker.value = selectedModel;
				} else {
					modelPicker.value = fallback;
				}
				if (typeof frappe !== "undefined" && frappe.set_route) {
					frappe.set_route("Form", "LLM Model", "new");
				}
				syncComposerFooterState();
				return;
			}
			selectedModel = v;
			localStorage.setItem(STORAGE_MODEL, selectedModel);
			appendTool("Model switched", selectedModel);
			syncComposerFooterState();
		});

		syncComposerFooterState();
		renderWelcome();
		loadModels();

		function applyEvents(events) {
			if (!events || !events.length) return;
			let textBuf = "";
			for (const evt of events) {
				if (evt.type === "text_delta") {
					textBuf += evt.delta || "";
				} else if (evt.type === "tool_use") {
					if (textBuf) {
						appendBubble("ai", escapeHtml(textBuf).replace(/\n/g, "<br/>"));
						textBuf = "";
					}
					appendTool("Tool: " + (evt.name || ""), JSON.stringify(evt.input || {}, null, 2));
				} else if (evt.type === "tool_result") {
					appendTool("Result: " + (evt.name || ""), JSON.stringify(evt.result || {}, null, 2));
				} else if (evt.type === "usage") {
					const cost =
						evt.cost_estimate != null ? " · $" + Number(evt.cost_estimate).toFixed(4) : "";
					appendTool(
						"Usage",
						(evt.model || "") + " · " + (evt.input_tokens || 0) + " in / " + (evt.output_tokens || 0) + " out" + cost
					);
				}
			}
			if (textBuf) {
				appendBubble("ai", escapeHtml(textBuf).replace(/\n/g, "<br/>"));
			}
		}

		async function send() {
			const text = (inp.value || "").trim();
			const attachmentsSnapshot = pendingAttachments.slice();
			if (!text && !attachmentsSnapshot.length) return;
			if (!hasSendableModel()) {
				if (typeof frappe !== "undefined" && frappe.show_alert) {
					frappe.show_alert({
						message: "Choose a model or open LLM Provider to add an API key.",
						indicator: "orange",
					});
				}
				return;
			}
			const modelLabel = selectedModel || modelPicker.value;
			if (!modelLabel || modelLabel === OPT_ADD_CUSTOM_MODEL) {
				if (typeof frappe !== "undefined" && frappe.show_alert) {
					frappe.show_alert({
						message: "Choose a model or open LLM Provider to add an API key.",
						indicator: "orange",
					});
				}
				return;
			}
			const welcomeEl = msgs.querySelector(".cad-empty");
			if (welcomeEl) welcomeEl.remove();
			syncComposerSetupBanner();
			inp.value = "";
			pendingAttachments = [];
			renderAttachmentStrip();
			let userBubbleHtml = text ? escapeHtml(text).replace(/\n/g, "<br/>") : "";
			if (attachmentsSnapshot.length) {
				const chips = attachmentsSnapshot
					.map(function (a) {
						return '<span class="cad-user-file-chip" role="listitem">' + escapeHtml(a.name || "file") + "</span>";
					})
					.join("");
				const block = '<div class="cad-user-attachments">' + chips + "</div>";
				userBubbleHtml = userBubbleHtml ? userBubbleHtml + "<br/>" + block : block;
			}
			appendBubble("user", userBubbleHtml);
			composerSendInFlight = true;
			sendBtn.disabled = true;
			try {
				const args = {
					message: text,
					conversation_id: conversationId,
					context: JSON.stringify(deskContext()),
					model_label: modelLabel,
				};
				if (attachmentsSnapshot.length) {
					args.attachments = JSON.stringify(attachmentsSnapshot);
				}
				const r = await frappe.call({
					method: "lazychat_mcp_erpnext.desk_assistant.api.send_message",
					args: args,
				});
				const msg = r.message || {};
				if (msg.conversation_id) conversationId = msg.conversation_id;
				applyEvents(msg.events);
			} catch (e) {
				appendBubble(
					"tool",
					"<strong>Error</strong><pre class='cad-raw'>" + escapeHtml(e.message || String(e)) + "</pre>"
				);
			} finally {
				composerSendInFlight = false;
				syncComposerFooterState();
				const fta = document.getElementById("cad-claude-float-ta");
				if (fta && document.activeElement === fta) {
					fta.focus();
					fta.style.height = "auto";
					fta.style.height = Math.min(fta.scrollHeight, 220) + "px";
				} else if (inp) {
					inp.focus();
					autosizeComposer();
				}
			}
		}
		sendBtn.addEventListener("click", send);
		function autosizeComposer() {
			const fta = document.getElementById("cad-claude-float-ta");
			if (fta && inp) fta.value = inp.value;
			if (!inp || inp.tagName !== "TEXTAREA") return;
			inp.style.height = "auto";
			const max = 220;
			inp.style.height = Math.min(inp.scrollHeight, max) + "px";
		}
		inp.addEventListener("input", autosizeComposer);
		inp.addEventListener("keydown", (ev) => {
			if (ev.key === "Enter" && !ev.shiftKey) {
				ev.preventDefault();
				send();
			}
		});
		autosizeComposer();

		/**
		 * Claude-style pill composer embedded in the dock footer (wires to dock textarea + send(); layered menus).
		 */
		function initCadDevShell() {
			const PLUS_SVG =
				'<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" d="M12 5v14M5 12h14"/></svg>';
			const CHEV_SVG =
				'<svg width="12" height="12" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M7 10l5 5 5-5H7z"/></svg>';
			const SEND_SVG =
				'<svg width="20" height="20" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" d="M12 19V5M5 12l7-7 7 7"/></svg>';
			const CHK_SVG =
				'<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" d="M6 12l4 4 8-8"/></svg>';

			function ensureDom() {
				if (document.getElementById("cad-claude-float-layer")) return;

				function iconSvg(iconName) {
					switch (iconName) {
						case "paperclip":
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"/></svg>';
						case "camera":
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="14" r="4" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
						case "github":
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M12 .5C5.65.5.5 5.65.5 12a11.5 11.5 0 007.86 10.9c.58.1.79-.25.79-.55l-.01-2c-3.2.69-3.89-1.54-3.89-1.54-.53-1.34-1.3-1.7-1.3-1.7-1.07-.74.08-.72.08-.72 1.19.08 1.81 1.22 1.81 1.22 1.05 1.8 2.75 1.28 3.42.98.1-.77.41-1.28.75-1.57-2.55-.29-5.23-1.28-5.23-5.7 0-1.26.45-2.29 1.2-3.1-.12-.29-.52-1.46.12-3.05 0 0 .97-.31 3.18 1.18a11 11 0 016 0c2.21-1.49 3.17-1.18 3.17-1.18.65 1.59.25 2.76.13 3.05.75.81 1.19 1.84 1.19 3.1 0 5.44-2.69 6.4-5.26 6.69.42.36.8 1.08.8 2.19l-.01 3.24c0 .3.2.66.8.55A11.5 11.5 0 0023.5 12 11.5 11.5 0 0012 .5z"/></svg>';
						case "grid":
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M4 4h6v6H4zm10 0h6v6h-6zM4 14h6v6H4zm10 0h6v6h-6z"/></svg>';
						case "spark":
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M11 21l1-7H6l9-13v13h5l-9 7z"/></svg>';
						case "globe":
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2"/><ellipse cx="12" cy="12" rx="9" ry="4" fill="none" stroke="currentColor" stroke-width="2"/><path fill="none" stroke="currentColor" stroke-width="2" d="M3 12h18"/></svg>';
						case "scroll":
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M8 4h8l2 3v14a2 2 0 01-2 2H8a2 2 0 01-2-2V7l2-3z"/><path fill="none" stroke="currentColor" stroke-width="2" d="M10 9h4"/></svg>';
						case "pen":
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M12 20h9M16.5 3.5l4 4L8 20H4v-4L16.5 3.5z"/></svg>';
						case "box":
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><path fill="none" stroke="currentColor" stroke-width="2" d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z"/><path fill="none" stroke="currentColor" stroke-width="2" d="M3.27 6.96L12 12l8.73-5.04"/></svg>';
						default:
							return '<svg width="18" height="18" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="2" fill="none" stroke="currentColor" stroke-width="2"/></svg>';
					}
				}

				function menuRow(iconName, label, id) {
					const ic = iconSvg(iconName);
					return (
						'<button type="button" role="menuitem" class="cad-claude-menu-item" id="' +
						id +
						'">' +
						'<span class="cad-claude-menu-ico">' +
						ic +
						"</span>" +
						'<span class="cad-claude-menu-txt">' +
						escapeHtml(label) +
						"</span>" +
						"</button>"
					);
				}

				function menuRowChev(iconName, label, id) {
					const row = menuRow(iconName, label, id);
					return row.replace("</button>", '<span class="cad-claude-menu-chev-r" aria-hidden="true">&rsaquo;</span></button>');
				}

				function menuRowActive(iconName, label, id) {
					const base = menuRow(iconName, label, id);
					return base
						.replace('class="cad-claude-menu-item"', 'class="cad-claude-menu-item cad-claude-menu-item--active"')
						.replace("</button>", '<span class="cad-claude-menu-check" aria-hidden="true">' + CHK_SVG + "</span></button>");
				}

				const layer = document.createElement("div");
				layer.id = "cad-claude-float-layer";
				layer.className = "cad-claude-float-layer cad-claude-float-layer--dock";
				layer.innerHTML =
					'<div class="cad-claude-float-anchor">' +
					'<div class="cad-claude-pill" role="presentation">' +
					'<textarea id="cad-claude-float-ta" class="cad-claude-float-ta" data-cad="inp" rows="1" ' +
					'placeholder="' +
					escapeHtml(__("Write Prompts here")) +
					'" autocomplete="off"></textarea>' +
					'<div class="cad-composer-attachments cad-claude-pill-attachments" data-cad="attachment-list" hidden role="list" aria-label="Pending attachments"></div>' +
					'<div class="cad-claude-pill-toolbar">' +
					'<div class="cad-claude-pill-toolbar-left">' +
					'<button type="button" class="cad-claude-btn-plus" data-cad-float="fab-plus" ' +
					'title="' +
					escapeHtml(__("Add")) +
					'" aria-label="' +
					escapeHtml(__("Add attachments and more")) +
					'" aria-expanded="false" aria-haspopup="true">' +
					PLUS_SVG +
					"</button>" +
					'<div class="cad-claude-plus-menu" data-cad-float="plus-menu" hidden role="menu">' +
					'<div class="cad-claude-menu-section">' +
					menuRow("paperclip", __("Add files or photos"), "cad-float-menu-files") +
					menuRow("camera", __("Take a screenshot"), "cad-float-menu-shot") +
					menuRowChev("box", __("Add to project"), "cad-float-menu-proj") +
					menuRow("github", __("Add from GitHub"), "cad-float-menu-gh") +
					"</div>" +
					'<div class="cad-claude-menu-divider" role="separator"></div>' +
					'<div class="cad-claude-menu-section">' +
					menuRowChev("scroll", __("Skills"), "cad-float-menu-skills") +
					menuRow("grid", __("Add connectors"), "cad-float-menu-conn") +
					"</div>" +
					'<div class="cad-claude-menu-divider" role="separator"></div>' +
					'<div class="cad-claude-menu-section">' +
					menuRow("spark", __("Research"), "cad-float-menu-research") +
					menuRowActive("globe", __("Web search"), "cad-float-menu-web") +
					menuRowChev("pen", __("Use style"), "cad-float-menu-style") +
					"</div>" +
					"</div>" +
					"</div>" +
					'<div class="cad-claude-pill-toolbar-right">' +
					'<button type="button" class="cad-claude-model-chip" data-cad-float="model-btn" ' +
					'aria-haspopup="listbox" aria-expanded="false" aria-label="' +
					escapeHtml(__("Choose model")) +
					'">' +
					'<span class="cad-claude-model-chip-main" data-cad-float="model-main"></span>' +
					'<span class="cad-claude-model-chip-sub" data-cad-float="model-sub"></span>' +
					'<span class="cad-claude-model-chip-chev" aria-hidden="true">' +
					CHEV_SVG +
					"</span>" +
					"</button>" +
					'<div class="cad-claude-model-menu" data-cad-float="model-menu" hidden role="listbox">' +
					'<div class="cad-claude-model-opt cad-claude-model-opt--head" data-cad-float="model-head">' +
					'<span class="cad-claude-model-opt-title" data-cad-float="model-opt-title"></span>' +
					'<span class="cad-claude-model-opt-desc">' +
					escapeHtml(__("Most capable for ambitious work")) +
					"</span>" +
					'<span class="cad-claude-model-opt-check" aria-hidden="true">' +
					CHK_SVG +
					"</span>" +
					"</div>" +
					'<div class="cad-claude-menu-divider" role="separator"></div>' +
					'<div class="cad-claude-model-opt cad-claude-model-opt--toggle" role="presentation">' +
					'<div><strong>' +
					escapeHtml(__("Adaptive thinking")) +
					'</strong><span class="cad-claude-model-opt-desc">' +
					escapeHtml(__("Thinks for more complex tasks")) +
					"</span></div>" +
					'<button type="button" class="cad-claude-toggle" data-cad-float="adapt-toggle" ' +
					'role="switch" aria-checked="true" aria-label="' +
					escapeHtml(__("Adaptive thinking")) +
					'"><span class="cad-claude-toggle-knob"></span></button>' +
					"</div>" +
					'<div class="cad-claude-menu-divider" role="separator"></div>' +
					'<button type="button" class="cad-claude-model-more" data-cad-float="model-more">' +
					escapeHtml(__("More models")) +
					'<span aria-hidden="true" class="cad-claude-chev-right">&rsaquo;</span>' +
					"</button>" +
					'<ul class="cad-claude-model-list-ul" data-cad-float="model-list-ul"></ul>' +
					"</div>" +
					'<button type="button" class="cad-claude-send-terra" data-cad-float="float-send" ' +
					'title="' +
					escapeHtml(__("Send")) +
					'" aria-label="' +
					escapeHtml(__("Send message")) +
					'">' +
					SEND_SVG +
					"</button>" +
					"</div>" +
					"</div>" +
					"</div>" +
					"</div>" +
					"</div>";

				composerFooter.appendChild(layer);
			}

			function splitModelLabel(s) {
				const t = (s || "").trim();
				if (!t) return { main: __("Select model"), sub: "" };
				const sp = t.lastIndexOf(" ");
				if (sp > 0 && sp < t.length - 1) {
					return { main: t.slice(0, sp), sub: t.slice(sp + 1) };
				}
				return { main: t, sub: "" };
			}

			function syncFloatModelChip() {
				const layer = document.getElementById("cad-claude-float-layer");
				if (!layer) return;
				const mainEl = layer.querySelector("[data-cad-float=\"model-main\"]");
				const subEl = layer.querySelector("[data-cad-float=\"model-sub\"]");
				const titleEl = layer.querySelector("[data-cad-float=\"model-opt-title\"]");
				const v = modelPicker.value;
				if (!v || v === OPT_ADD_CUSTOM_MODEL) {
					if (mainEl) {
						mainEl.textContent = __("Select model");
						mainEl.classList.add("cad-claude-model-chip-main--muted");
					}
					if (subEl) {
						subEl.textContent = "";
						subEl.hidden = true;
					}
					if (titleEl) titleEl.textContent = __("Select model");
					return;
				}
				const parts = splitModelLabel(v);
				if (mainEl) {
					mainEl.textContent = parts.main;
					mainEl.classList.remove("cad-claude-model-chip-main--muted");
				}
				if (subEl) {
					subEl.textContent = parts.sub || "";
					subEl.hidden = !parts.sub;
				}
				if (titleEl) titleEl.textContent = parts.main;
			}

			function rebuildModelListUl() {
				const layer = document.getElementById("cad-claude-float-layer");
				if (!layer) return;
				const ul = layer.querySelector("[data-cad-float=\"model-list-ul\"]");
				if (!ul) return;
				ul.innerHTML = "";
				Array.from(modelPicker.options).forEach(function (opt) {
					const val = opt.value;
					if (!val || val === OPT_ADD_CUSTOM_MODEL || opt.disabled) return;
					const li = document.createElement("li");
					const btn = document.createElement("button");
					btn.type = "button";
					btn.role = "option";
					btn.className = "cad-claude-model-li-btn";
					btn.setAttribute("data-value", val);
					btn.textContent = opt.textContent || val;
					if (val === modelPicker.value) btn.setAttribute("aria-selected", "true");
					li.appendChild(btn);
					ul.appendChild(li);
				});
			}

			function closeMenus() {
				const layer = document.getElementById("cad-claude-float-layer");
				if (!layer) return;
				const pm = layer.querySelector("[data-cad-float=\"plus-menu\"]");
				const mm = layer.querySelector("[data-cad-float=\"model-menu\"]");
				const fb = layer.querySelector("[data-cad-float=\"fab-plus\"]");
				const mb = layer.querySelector("[data-cad-float=\"model-btn\"]");
				if (pm) pm.hidden = true;
				if (mm) mm.hidden = true;
				if (fb) fb.setAttribute("aria-expanded", "false");
				if (mb) mb.setAttribute("aria-expanded", "false");
			}

			function autosizeFloatTa(ta) {
				if (!ta || ta.tagName !== "TEXTAREA") return;
				ta.style.height = "auto";
				const max = 220;
				ta.style.height = Math.min(ta.scrollHeight, max) + "px";
			}

			ensureDom();

			const layerEl = document.getElementById("cad-claude-float-layer");
			const floatTa = document.getElementById("cad-claude-float-ta");
			const floatSend = layerEl && layerEl.querySelector("[data-cad-float=\"float-send\"]");
			const fabPlus = layerEl && layerEl.querySelector("[data-cad-float=\"fab-plus\"]");
			const plusMenu = layerEl && layerEl.querySelector("[data-cad-float=\"plus-menu\"]");
			const modelBtn = layerEl && layerEl.querySelector("[data-cad-float=\"model-btn\"]");
			const modelMenu = layerEl && layerEl.querySelector("[data-cad-float=\"model-menu\"]");
			const modelMore = layerEl && layerEl.querySelector("[data-cad-float=\"model-more\"]");
			const modelListUl = layerEl && layerEl.querySelector("[data-cad-float=\"model-list-ul\"]");

			if (floatTa) {
				floatTa.addEventListener("input", function () {
					autosizeComposer();
					autosizeFloatTa(floatTa);
				});
				floatTa.addEventListener("keydown", function (ev) {
					if (ev.key === "Enter" && !ev.shiftKey) {
						ev.preventDefault();
						send();
						floatTa.value = "";
						autosizeFloatTa(floatTa);
					}
				});
			}

			if (floatSend) {
				floatSend.addEventListener("click", function () {
					send();
					if (floatTa) {
						floatTa.value = "";
						autosizeFloatTa(floatTa);
					}
				});
			}

			if (fabPlus && plusMenu) {
				fabPlus.addEventListener("click", function (ev) {
					ev.stopPropagation();
					const open = plusMenu.hidden;
					closeMenus();
					if (open) {
						plusMenu.hidden = false;
						fabPlus.setAttribute("aria-expanded", "true");
					}
				});
			}

			if (modelBtn && modelMenu) {
				modelBtn.addEventListener("click", function (ev) {
					ev.stopPropagation();
					const open = modelMenu.hidden;
					closeMenus();
					syncFloatModelChip();
					rebuildModelListUl();
					if (open) {
						modelMenu.hidden = false;
						modelBtn.setAttribute("aria-expanded", "true");
					}
				});
			}

			document.addEventListener("click", function (ev) {
				if (!layerEl) return;
				if (layerEl.contains(ev.target)) return;
				closeMenus();
			});

			document.addEventListener("keydown", function (ev) {
				if (ev.key === "Escape") closeMenus();
			});

			if (plusMenu) {
				plusMenu.addEventListener("click", function (ev) {
					const btn = ev.target && ev.target.closest("button.cad-claude-menu-item");
					if (!btn || !plusMenu.contains(btn)) return;
					const id = btn.id;
					closeMenus();
					if (id === "cad-float-menu-files") {
						if (fileInput) fileInput.click();
						return;
					}
					if (typeof frappe !== "undefined" && frappe.show_alert) {
						frappe.show_alert({
							message: __("Coming soon — use the desk assistant menu for full actions."),
							indicator: "blue",
						});
					}
				});
			}

			if (modelMore) {
				modelMore.addEventListener("click", function () {
					modelMenu.hidden = true;
					modelBtn.setAttribute("aria-expanded", "false");
					modelPicker.focus();
					try {
						modelPicker.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
						modelPicker.click();
					} catch (e) {
						modelPicker.focus();
					}
				});
			}

			if (modelListUl) {
				modelListUl.addEventListener("click", function (ev) {
					const b = ev.target && ev.target.closest(".cad-claude-model-li-btn");
					if (!b || !modelListUl.contains(b)) return;
					const val = b.getAttribute("data-value");
					if (!val) return;
					modelPicker.value = val;
					modelPicker.dispatchEvent(new Event("change", { bubbles: true }));
					closeMenus();
					syncFloatModelChip();
				});
			}

			modelPicker.addEventListener("change", syncFloatModelChip);

			const adaptToggle = layerEl && layerEl.querySelector("[data-cad-float=\"adapt-toggle\"]");
			if (adaptToggle) {
				adaptToggle.addEventListener("click", function (e) {
					e.preventDefault();
					e.stopPropagation();
					const on = adaptToggle.getAttribute("aria-checked") !== "false";
					adaptToggle.setAttribute("aria-checked", on ? "false" : "true");
					adaptToggle.classList.toggle("cad-claude-toggle--off", on);
				});
			}

			window.__cad_on_models_loaded = function () {
				syncFloatModelChip();
				rebuildModelListUl();
			};

			syncFloatModelChip();
		}

		if (typeof frappe !== "undefined" && frappe.router && typeof frappe.router.on === "function") {
			frappe.router.on("change", function () {
				setTimeout(renderCtx, 0);
			});
		}
		if (typeof jQuery !== "undefined") {
			jQuery(document).on("page-change", function () {
				setTimeout(renderCtx, 0);
			});
		}

		console.info("[lazychat_mcp_erpnext] desk dock mounted (layout v3 composer)");
	}

	function scheduleMount() {
		const run = () => {
			const dock = document.getElementById("claude-assistant-dock");
			if (dock && dock.getAttribute("data-cad-layout") === "v3") {
				return;
			}
			try {
				tryMountDeskAssistant();
			} catch (e) {
				console.error("[lazychat_mcp_erpnext] desk mount failed", e);
			}
		};
		if (typeof frappe !== "undefined" && typeof frappe.ready === "function") {
			frappe.ready(run);
		}
		if (typeof jQuery !== "undefined") {
			/* Desk fires `app_ready` once Application has set globals — run after paint */
			jQuery(document).on("app_ready", function () {
				requestAnimationFrame(function () {
					setTimeout(run, 0);
				});
			});
			jQuery(document).on("startup", function () {
				setTimeout(run, 0);
			});
			jQuery(run);
			jQuery(document).on("page-change", function () {
				setTimeout(run, 0);
			});
		}
		if (typeof frappe !== "undefined" && frappe.router && typeof frappe.router.on === "function") {
			frappe.router.on("change", function () {
				setTimeout(run, 50);
			});
		}
		setTimeout(run, 0);
		setTimeout(run, 500);
		setTimeout(run, 2000);
		/* Last resort if another script or timing prevented earlier mounts */
		let n = 0;
		const poll = setInterval(function () {
			n += 1;
			if (document.getElementById("claude-assistant-dock") || n > 60) {
				clearInterval(poll);
				return;
			}
			run();
		}, 500);
	}

	scheduleMount();
})();
