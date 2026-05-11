/**
 * LLM Provider — API Key field uses Frappe Password control, which:
 * - Keeps the eye hidden when a value already exists (!this.value guard).
 * - Hides the eye when the value contains "*" (keyup).
 * - Runs password-strength UI meant for User passwords.
 * - After save, the DOM usually holds a mask (***…), not the real key — reveal uses a whitelisted API.
 *
 * We patch once at ControlPassword.make_input and also re-wire on refresh with retries,
 * replace the stock eye with a reliable button, and stop keyup from fighting visibility.
 */
(function () {
	let llm_provider_handlers_registered = false;

	function is_llm_provider_api_key(ctrl) {
		if (!ctrl || !ctrl.df || ctrl.df.fieldname !== "api_key") return false;
		// During ControlPassword.make_input(), frm is sometimes not attached yet — use DocField parent.
		const parent_dt =
			ctrl.df.parent ||
			(ctrl.frm && ctrl.frm.doctype) ||
			(ctrl.frm && ctrl.frm.meta && ctrl.frm.meta.name);
		return parent_dt === "LLM Provider";
	}

	function icon_show() {
		if (frappe.utils && frappe.utils.icon) {
			return frappe.utils.icon("unhide", "sm") || frappe.utils.icon("eye", "sm");
		}
		return '<span aria-hidden="true">👁</span>';
	}

	function icon_hide() {
		if (frappe.utils && frappe.utils.icon) {
			return frappe.utils.icon("hide", "sm") || frappe.utils.icon("eye-off", "sm");
		}
		return '<span aria-hidden="true">🙈</span>';
	}

	/** True when the field shows Frappe’s saved-password mask (not the real secret in DOM). */
	function looks_masked_api_key_display(val) {
		const t = String(val || "").trim();
		if (!t) return true;
		if (/^[\s*•]+$/.test(t)) return true;
		return false;
	}

	function resolve_llm_api_key_input(ctrl) {
		const $w = ctrl.$wrapper && ctrl.$wrapper.length ? ctrl.$wrapper : $(ctrl.wrapper);
		let $inp = $w.find('.control-input input[data-fieldname="api_key"]').first();
		if (!$inp.length) {
			$inp = $w.find(".control-input input.form-control").first();
		}
		if (!$inp.length && ctrl.$input && ctrl.$input.length) {
			$inp = ctrl.$input;
		}
		return $inp;
	}

	function wire_llm_api_key_control(ctrl) {
		if (!is_llm_provider_api_key(ctrl)) return;

		const $inp_live = resolve_llm_api_key_input(ctrl);
		if (!$inp_live || !$inp_live.length) return;

		if (typeof ctrl.disable_password_checks === "function") {
			ctrl.disable_password_checks();
		}
		/* Stop stock Password control from hiding the eye / fighting visibility */
		$inp_live.off("keyup");
		if (ctrl.$input && ctrl.$input.length) {
			ctrl.$input.off("keyup");
		}

		if (ctrl.indicator && ctrl.indicator.length) {
			ctrl.indicator.addClass("hidden");
		}
		ctrl.$wrapper.find(".password-strength-indicator").addClass("hidden");
		ctrl.$wrapper.find(".help-box").first().addClass("hidden");

		let $wrap = ctrl.$wrapper.find(".control-input").first();
		if (!$wrap.length && ctrl.$input && ctrl.$input.length) {
			$wrap = ctrl.$input.parent();
		}
		if (!$wrap.length) return;

		$wrap.css("position", "relative");

		// Drop Frappe's toggle — we replace it so behaviour does not depend on version flags.
		$wrap.find(".toggle-password").remove();

		const $dup_toggles = $wrap.find(".cad-api-key-toggle");
		if ($dup_toggles.length > 1) {
			$dup_toggles.slice(1).remove();
		}

		let $btn = $wrap.find(".cad-api-key-toggle").first();
		if (!$btn.length) {
			$btn = $('<button type="button" class="cad-api-key-toggle btn btn-default btn-xs"></button>');
			$btn.attr("aria-label", __("Show or hide API key"));
			$btn.attr("title", __("Show or hide API key"));
		}
		$btn.insertAfter($inp_live);

		function sync($inp) {
			const $field = $inp && $inp.length ? $inp : resolve_llm_api_key_input(ctrl);
			const is_pw = ($field.attr("type") || "") === "password";
			$btn.html(is_pw ? icon_show() : icon_hide());
			$btn.attr("aria-pressed", is_pw ? "false" : "true");
		}

		$btn.off("click.cad_api_key");
		$btn.on("click.cad_api_key", function (ev) {
			ev.preventDefault();
			ev.stopPropagation();
			if (typeof ev.stopImmediatePropagation === "function") {
				ev.stopImmediatePropagation();
			}
			const $field = resolve_llm_api_key_input(ctrl);
			if (!$field.length) return;

			const frm = ctrl.frm;
			const is_pw = ($field.attr("type") || "") === "password";
			const switching_to_text = is_pw;

			/* Saved doc + mask in DOM: fetch real key (Password fields never embed it client-side). */
			if (
				switching_to_text &&
				frm &&
				frm.doc &&
				frm.doc.name &&
				typeof frm.is_new === "function" &&
				!frm.is_new() &&
				looks_masked_api_key_display($field.val())
			) {
				frappe.call({
					method: "lazychat_erpnext.desk_assistant.api.reveal_llm_provider_api_key",
					args: { provider_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Loading API key…"),
					callback(r) {
						if (r.exc) return;
						const k =
							r.message && r.message.api_key != null ? String(r.message.api_key) : "";
						$field.val(k);
						$field.attr("type", "text");
						$field.css("-webkit-text-security", "none");
						sync($field);
					},
				});
				return;
			}

			const next = is_pw ? "text" : "password";
			$field.attr("type", next);
			/* Some WebKit paths honor text-security even when type is text */
			if (next === "text") {
				$field.css("-webkit-text-security", "none");
			} else {
				$field.css("-webkit-text-security", "");
			}
			sync($field);
		});

		sync($inp_live);
	}

	function patch_control_password() {
		const CPP = frappe.ui.form.ControlPassword;
		if (!CPP || !CPP.prototype || CPP.prototype._cad_llm_api_key_patched) return;
		CPP.prototype._cad_llm_api_key_patched = true;

		const orig = CPP.prototype.make_input;
		CPP.prototype.make_input = function () {
			orig.apply(this, arguments);
			wire_llm_api_key_control(this);
		};
	}

	function wire_from_form(frm) {
		const c = frm.fields_dict && frm.fields_dict.api_key;
		if (c) {
			wire_llm_api_key_control(c);
		}
	}

	/** Suggest a unique-ish Model Label from provider + model id (user can edit on LLM Model). */
	function safe_model_label(providerName, modelId) {
		const a = String(providerName || "model")
			.replace(/[^\w\s.-]+/g, "")
			.trim()
			.replace(/\s+/g, "-");
		const b = String(modelId || "")
			.replace(/[^\w.:/-]+/g, "-")
			.replace(/[/:]/g, "-");
		const combined = (a + "-" + b).replace(/-+/g, "-");
		return combined.slice(0, 120) || b || "model";
	}

	function escapeHtmlDesk(s) {
		if (frappe.utils && typeof frappe.utils.escape_html === "function") {
			return frappe.utils.escape_html(s == null ? "" : String(s));
		}
		const d = document.createElement("div");
		d.textContent = s == null ? "" : String(s);
		return d.innerHTML;
	}

	function runProviderConnectionTest(frm) {
		if (frm.is_new() || !frm.doc.name) {
			frappe.show_alert({
				message: __("Save the provider before testing the connection."),
				indicator: "orange",
			});
			return;
		}
		frappe.call({
			method: "lazychat_erpnext.desk_assistant.api.test_llm_provider_connection",
			args: { provider_name: frm.doc.name },
			freeze: true,
			freeze_message: __("Testing API connection…"),
			callback(r) {
				if (r.exc) {
					frappe.msgprint({
						title: __("Connection test"),
						message: r.exc,
						indicator: "red",
					});
					return;
				}
				const m = r.message || {};
				let body = escapeHtmlDesk(m.message || "");
				if (m.endpoint) {
					body +=
						'<p class="text-muted small" style="margin-top:10px;margin-bottom:0">' +
						escapeHtmlDesk(__("Endpoint")) +
						": " +
						escapeHtmlDesk(m.endpoint) +
						"</p>";
				}
				frappe.msgprint({
					title: m.title || (m.ok ? __("Connection OK") : __("Connection failed")),
					message: body,
					indicator: m.ok ? "green" : "red",
				});
			},
		});
	}

	function wire_connection_models_panel(frm) {
		if (!frm || !frm.fields_dict || !frm.fields_dict.api_key) return;
		const $api = frm.fields_dict.api_key.$wrapper;
		if (!$api || !$api.length) return;
		const $anchor = $api.closest(".frappe-control");
		if (!$anchor || !$anchor.length) return;

		$anchor.next(".cad-provider-models-panel").remove();

		const canFetch = !frm.is_new() && frm.doc && frm.doc.name;
		const hintSave = canFetch
			? ""
			: `<p class="help-box small text-muted cad-save-first-hint">${__(
					"Save this provider first — then use Fetch models."
			  )}</p>`;

		const uid = frm.doc && frm.doc.name ? frm.doc.name.replace(/[^\w-]/g, "_") : "new";

		const html = `
<div class="cad-provider-models-panel llm-setup-callout">
	<div class="row cad-provider-models-intro-row">
	<div class="col-12">
		<label class="control-label">${__("Desk models")}</label>
		<p class="help-box small">${__(
			"Pick or type a vendor Model ID, then Add LLM Model to register it as a desk row. Saving this provider stores your draft Model ID (staging) — it is not the same as creating an LLM Model."
		)}</p>
		${hintSave}
	</div>
	</div>
	<div class="row cad-provider-models-toolbar-row">
	<div class="col-12 col-lg-7 cad-provider-models-select-wrap">
		<label class="cad-provider-models-subtle-label" for="cad-model-combobox-trigger-${uid}">${__("From API")}</label>
		<div class="cad-model-combobox" data-cad-model-combobox="${uid}">
			<div class="cad-model-combobox-inner">
				<button
					type="button"
					id="cad-model-combobox-trigger-${uid}"
					class="cad-model-combobox-trigger"
					aria-haspopup="listbox"
					aria-expanded="false"
					aria-controls="cad-model-combobox-list-${uid}"
				>
					<span class="cad-model-combobox-value cad-model-combobox-value--placeholder">${__(
						"Select a model ID…"
					)}</span>
					<span class="cad-model-combobox-chevron" aria-hidden="true"
						><svg width="14" height="14" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M6 9l6 6 6-6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg
					></span>
				</button>
				<div class="cad-model-combobox-dropdown" id="cad-model-combobox-dropdown-${uid}" hidden>
					<input
						type="search"
						class="cad-model-combobox-search form-control input-sm"
						id="cad-model-combobox-search-${uid}"
						placeholder="${__("Search models…")}"
						autocomplete="off"
						aria-label="${__("Filter model list")}"
					/>
					<ul class="cad-model-combobox-list" id="cad-model-combobox-list-${uid}" role="listbox"></ul>
					<p class="cad-model-combobox-empty help-box small" hidden role="status">${__(
						"No matching models."
					)}</p>
				</div>
			</div>
		</div>
	</div>
	<div class="col-12 col-lg-5 cad-provider-models-actions" role="group" aria-label="${__("Desk model actions")}">
		<button type="button" class="btn btn-default btn-sm cad-fetch-remote-models" ${canFetch ? "" : "disabled"}>${__(
			"Fetch models"
		)}</button>
		<button type="button" class="btn btn-primary btn-sm cad-create-llm-model-from-picker">${__("Add LLM Model…")}</button>
	</div>
	</div>
	<div class="row cad-provider-models-manual-row">
	<div class="col-12 cad-provider-models-manual-wrap">
		<label class="cad-provider-models-subtle-label" for="cad-provider-model-manual-${uid}">${__(
			"Or type Model ID"
		)}</label>
		<input
			id="cad-provider-model-manual-${uid}"
			type="text"
			class="form-control input-sm cad-provider-model-manual"
			placeholder="${__("e.g. meta/llama-3.3-70b-instruct")}"
			autocomplete="off"
			spellcheck="false"
			aria-label="${__("Vendor model id if not in list")}"
		/>
	</div>
	</div>
	<div class="row cad-provider-models-hint-row">
	<div class="col-12">
		<p class="cad-provider-models-hint help-box small" style="display:none" role="status"></p>
	</div>
	</div>
</div>`;
		$(document).off(".cad_mcombo_" + uid);
		$anchor.after(html);

		const $panel = $anchor.next(".cad-provider-models-panel");
		const $comboRoot = $panel.find(".cad-model-combobox");
		const $comboInner = $panel.find(".cad-model-combobox-inner");
		const $trigger = $panel.find(".cad-model-combobox-trigger");
		const $dropdown = $panel.find(".cad-model-combobox-dropdown");
		const $search = $panel.find(".cad-model-combobox-search");
		const $list = $panel.find(".cad-model-combobox-list");
		const $empty = $panel.find(".cad-model-combobox-empty");
		const $valueSpan = $panel.find(".cad-model-combobox-value");
		const $manual = $panel.find(".cad-provider-model-manual");
		const $hint = $panel.find(".cad-provider-models-hint");
		const $fetchBtn = $panel.find(".cad-fetch-remote-models");

		let comboModels = [];
		let comboSelected = "";
		let comboSearchTimer = null;
		let manualStagingTimer = null;

		function modelsStorageKey() {
			const n = frm.doc && frm.doc.name ? String(frm.doc.name) : "";
			return "cad_llm_provider_remote_models_" + (n || "new");
		}

		function saveModelsToSessionStorage() {
			try {
				if (!frm.doc || !frm.doc.name || !comboModels.length) return;
				sessionStorage.setItem(
					modelsStorageKey(),
					JSON.stringify({ ids: comboModels.slice(), ts: Date.now() })
				);
			} catch (e) {
				/* ignore quota / private mode */
			}
		}

		function loadModelsFromSessionStorage() {
			try {
				const raw = sessionStorage.getItem(modelsStorageKey());
				if (!raw) return;
				const o = JSON.parse(raw);
				if (o && Array.isArray(o.ids) && o.ids.length) {
					comboModels = o.ids.filter(Boolean);
				}
			} catch (e) {
				/* ignore */
			}
		}

		loadModelsFromSessionStorage();

		function canPersistStaging() {
			if (!frm) return false;
			if (frm.read_only) return false;
			if (frm.perm && frm.perm[0] && frm.perm[0].write === 0) return false;
			return !!(frm.fields_dict && frm.fields_dict.staging_model_id);
		}

		function persistStagingToDoc(mid) {
			if (!canPersistStaging()) return;
			const v = (mid || "").trim();
			const cur =
				frm.doc.staging_model_id != null ? String(frm.doc.staging_model_id).trim() : "";
			if (cur === v) return;
			frm.set_value("staging_model_id", v);
		}

		function resolvedModelId() {
			const fromCombo = (comboSelected || "").trim();
			const typed = ($manual.val() || "").trim();
			if (fromCombo) return fromCombo;
			return typed;
		}

		function setComboValue(id, skipPersist) {
			comboSelected = (id || "").trim();
			if (!comboSelected) {
				$valueSpan.text(__("Select a model ID…"));
				$valueSpan.addClass("cad-model-combobox-value--placeholder");
			} else {
				$valueSpan.text(comboSelected);
				$valueSpan.removeClass("cad-model-combobox-value--placeholder");
			}
			if (!skipPersist) {
				persistStagingToDoc(resolvedModelId());
			}
		}

		function applySavedStagingFromDoc() {
			const stagedFromDoc = frm.doc && frm.doc.staging_model_id ? String(frm.doc.staging_model_id).trim() : "";
			if (!stagedFromDoc) return;
			if (comboModels.length && comboModels.indexOf(stagedFromDoc) !== -1) {
				setComboValue(stagedFromDoc, true);
				$manual.val("");
			} else {
				setComboValue("", true);
				$manual.val(stagedFromDoc);
			}
		}

		applySavedStagingFromDoc();

		function renderComboList(filterStr) {
			const q = (filterStr || "").trim().toLowerCase();
			const filtered = !q ? comboModels : comboModels.filter(function (mid) {
				return mid.toLowerCase().indexOf(q) !== -1;
			});
			$list.empty();
			filtered.forEach(function (mid) {
				const $opt = $("<li>", {
					class: "cad-model-combobox-option",
					role: "option",
					tabindex: -1,
					text: mid,
				}).attr("data-value", mid);
				if (mid === comboSelected) {
					$opt.attr("aria-selected", "true");
				}
				$list.append($opt);
			});
			const showNoMatch = filtered.length === 0 && comboModels.length > 0;
			$empty.toggle(showNoMatch);
		}

		function closeCombo() {
			$dropdown.prop("hidden", true);
			$trigger.attr("aria-expanded", "false");
			$comboInner.removeClass("is-open");
			$search.val("");
			$list.empty();
			$empty.prop("hidden", true);
			$(document).off(".cad_mcombo_" + uid);
		}

		function openCombo() {
			if (!comboModels.length) {
				frappe.show_alert({
					message: __("Fetch models first, then pick from the list."),
					indicator: "orange",
				});
				return;
			}
			$(document).off(".cad_mcombo_" + uid);
			$comboInner.addClass("is-open");
			$dropdown.prop("hidden", false);
			$trigger.attr("aria-expanded", "true");
			renderComboList($search.val());
			setTimeout(function () {
				$search.trigger("focus");
			}, 0);
			$(document).on("click.cad_mcombo_" + uid, function (ev) {
				if ($comboRoot.length && !$comboRoot[0].contains(ev.target)) {
					closeCombo();
				}
			});
			$(document).on("keydown.cad_mcombo_" + uid, function (ev) {
				if (ev.key === "Escape") {
					closeCombo();
					ev.preventDefault();
				}
			});
		}

		$trigger.off("click.cad_combo").on("click.cad_combo", function (ev) {
			ev.preventDefault();
			ev.stopPropagation();
			if ($dropdown.prop("hidden")) {
				openCombo();
			} else {
				closeCombo();
			}
		});

		$list.off(".cad_combo_opts").on("click.cad_combo_opts", "li.cad-model-combobox-option", function () {
			const mid = ($(this).attr("data-value") || $(this).text() || "").trim();
			setComboValue(mid);
			closeCombo();
		});

		$search.off("input.cad_combo").on("input.cad_combo", function () {
			clearTimeout(comboSearchTimer);
			comboSearchTimer = setTimeout(function () {
				renderComboList($search.val());
			}, 120);
		});

		$search.off("keydown.cad_combo").on("keydown.cad_combo", function (ev) {
			if (ev.key === "Enter") {
				const $opts = $list.find(".cad-model-combobox-option");
				if ($opts.length === 1) {
					const mid = ($opts.first().attr("data-value") || "").trim();
					setComboValue(mid);
					closeCombo();
					ev.preventDefault();
				}
			}
		});

		$manual.off("input.cad_staging").on("input.cad_staging", function () {
			clearTimeout(manualStagingTimer);
			manualStagingTimer = setTimeout(function () {
				persistStagingToDoc(resolvedModelId());
			}, 220);
		});

		function showHint(text, isWarn) {
			if (!text) {
				$hint.hide().text("");
				return;
			}
			$hint
				.show()
				.text(text)
				.toggleClass("text-warning", !!isWarn)
				.removeClass("text-muted");
			if (!isWarn) {
				$hint.addClass("text-muted");
			}
		}

		$fetchBtn.off("click.cad_models").on("click.cad_models", function () {
			if (!canFetch) {
				frappe.show_alert({
					message: __("Save the provider document first."),
					indicator: "orange",
				});
				return;
			}
			frappe.call({
				method: "lazychat_erpnext.desk_assistant.api.discover_remote_models",
				args: { provider_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Fetching models…"),
				callback(r) {
					const msg = r.message || {};
					const models = msg.models || [];
					comboModels = [];
					models.forEach(function (row) {
						const id = row.id || "";
						if (!id) return;
						comboModels.push(id);
					});
					saveModelsToSessionStorage();
					comboSelected = "";
					setComboValue("", true);
					const savedStaging =
						frm.doc && frm.doc.staging_model_id
							? String(frm.doc.staging_model_id).trim()
							: "";
					if (savedStaging) {
						if (comboModels.indexOf(savedStaging) !== -1) {
							setComboValue(savedStaging, true);
							$manual.val("");
						} else {
							setComboValue("", true);
							$manual.val(savedStaging);
						}
					} else {
						$manual.val("");
					}
					if (!$dropdown.prop("hidden")) {
						renderComboList($search.val());
					}
					if (msg.error) {
						showHint(msg.error, true);
					} else {
						showHint("", false);
					}
					if (models.length) {
						frappe.show_alert({
							message: models.length + " " + __("models loaded"),
							indicator: "green",
						});
					} else if (!msg.ok) {
						frappe.show_alert({
							message:
								(msg.error || __("No models returned")) +
								" " +
								__("You can still type a Model ID below."),
							indicator: "orange",
						});
					}
				},
			});
		});

		$panel.find(".cad-create-llm-model-from-picker").off("click.cad_models").on("click.cad_models", function () {
			const mid = resolvedModelId();
			if (!mid) {
				frappe.msgprint({
					title: __("Model ID"),
					message: __(
						"Choose a model in the list, type a Model ID in the text field, or run Fetch models."
					),
					indicator: "orange",
				});
				return;
			}
			if (frm.is_new() || !frm.doc.name) {
				frappe.show_alert({
					message: __("Save the provider before creating a linked LLM Model."),
					indicator: "orange",
				});
				return;
			}
			const label = safe_model_label(frm.doc.provider_name, mid);
			sessionStorage.setItem(
				"lazychat_erpnext_llm_model_prefill",
				JSON.stringify({
					provider: frm.doc.name,
					model_id: mid,
					model_label: label,
				})
			);
			frappe.new_doc("LLM Model");
		});
	}

	function bootstrap_patch() {
		if (typeof frappe === "undefined" || !frappe.ui || !frappe.ui.form) return;
		if (!frappe.ui.form.ControlPassword) return;
		patch_control_password();
	}

	function register_llm_provider_handlers() {
		if (llm_provider_handlers_registered) return;
		if (typeof frappe === "undefined" || !frappe.ui || !frappe.ui.form || !frappe.ui.form.on) return;

		frappe.ui.form.on("LLM Provider", {
			onload() {
				bootstrap_patch();
			},

			refresh(frm) {
				const delays = [0, 50, 150, 400, 800];
				delays.forEach((ms) => setTimeout(() => wire_from_form(frm), ms));
				[0, 120, 400].forEach((ms) => setTimeout(() => wire_connection_models_panel(frm), ms));

				frm.page.add_inner_button(__("Test connection"), function () {
					runProviderConnectionTest(frm);
				});

				const raw = sessionStorage.getItem("lazychat_erpnext_llm_prefill");
				if (raw && frm.is_new()) {
					try {
						const p = JSON.parse(raw);
						sessionStorage.removeItem("lazychat_erpnext_llm_prefill");
						if (p.provider_name) frm.set_value("provider_name", p.provider_name);
						if (p.provider_type) frm.set_value("provider_type", p.provider_type);
						if (p.base_url) frm.set_value("base_url", p.base_url);
						if (p.api_key) frm.set_value("api_key", p.api_key);
						frm.clear_table("http_headers");
						Object.keys(p.headers || {}).forEach((k) => {
							const row = frm.add_child("http_headers");
							row.header_key = k;
							row.header_value = p.headers[k];
						});
						frm.refresh_field("http_headers");
						frappe.show_alert({
							message: __("Prefilled from cURL — review and Save."),
							indicator: "green",
						});
					} catch (e) {
						sessionStorage.removeItem("lazychat_erpnext_llm_prefill");
					}
				}

				frm.add_custom_button(
					__("Import from cURL"),
					() => {
						const d = lazychat_erpnext.llm_setup.wrapSetupDialog(
							new frappe.ui.Dialog({
								title: __("Import from cURL"),
								fields: [
									{
										fieldtype: "Small Text",
										fieldname: "hint",
										read_only: 1,
										default: __(
											"Paste a full curl (URL + -H headers). Bearer / x-api-key map to API Key; other headers go to the table."
										),
									},
									{
										fieldtype: "Long Text",
										fieldname: "curl",
										label: __("cURL"),
										reqd: 1,
									},
								],
								primary_action_label: __("Apply"),
								primary_action(values) {
									const parsed = lazychat_erpnext.llm_setup.parseCurl(values.curl || "");
									d.hide();
									lazychat_erpnext.llm_setup.applyParsedToProviderForm(frm, parsed);
								},
							})
						);
						d.show();
					},
					__("Tools")
				);

				frm.add_custom_button(
					__("Add OpenRouter headers"),
					() => {
						frm.add_child("http_headers", {
							header_key: "HTTP-Referer",
							header_value: "https://openrouter.ai/",
						});
						frm.add_child("http_headers", {
							header_key: "X-Title",
							header_value: "ERPNext Desk",
						});
						frm.refresh_field("http_headers");
					},
					__("Tools")
				);
			},

			api_key(frm) {
				wire_from_form(frm);
				setTimeout(() => wire_connection_models_panel(frm), 0);
			},
		});

		llm_provider_handlers_registered = true;
	}

	function init_llm_provider_password_ui() {
		bootstrap_patch();
		register_llm_provider_handlers();
	}

	if (typeof frappe !== "undefined" && frappe.ready) {
		frappe.ready(init_llm_provider_password_ui);
	}
	init_llm_provider_password_ui();
	setTimeout(init_llm_provider_password_ui, 0);
})();
