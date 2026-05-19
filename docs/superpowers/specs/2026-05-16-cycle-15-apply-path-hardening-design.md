# Cycle 15 — Apply-path hardening (URL slugs · duplicate pivot · token TTL · turn budget)

**Date:** 2026-05-16
**Trigger:** Real-user transcript on `claude-haiku-latest` model attempting to create a custom Purchase Order Print Format ("Purchase Order - Agilitas") from an uploaded PDF mockup. Flow degraded across 4 independent failure modes; user got stuck with no Apply card visible and no actionable feedback.
**Companion repo:** [lazychat.ai](../../../../lazychat.ai/) — Bug 4's chat-ui detection lives there.
**Tag target:** `cycle-15`. Backend `0.5.0`, chat-ui `0.2.0`.

---

## Why

The user uploaded `PO-M26-02-000400.pdf` and asked "Create Purchase Order Print format for purchase order doctype print format name- 'Purchase Order - Agilitas'". The agent (Claude Haiku):

1. Successfully discovered the doctype (`describe_doctype`) — fine.
2. Tried `prepare_create_print_format` with various Jinja templates; several failed Jinja validation; one eventually succeeded with `Applied · create_print_format` ✓.
3. Clicked the "Open Print Format" CTA → landed on `http://localhost:8000/app/print_format/Purchase%20Order%20-%20Agilitas` → **HTTP 404 "Page print_format not found"**.
4. User asked the agent to enhance the print format. Agent called `prepare_update_doc` → failed with "Print Format 'Purchase Order - Agilitas' does not exist." (Token-route issue, not doc-existence.)
5. Agent fell back to `prepare_create_print_format` → IntegrityError 1062 Duplicate entry.
6. Re-attempted update → "Token not found, expired, or not yours" (token expired during the loop).
7. After several more failed turns, the agent stopped emitting `prepare_*` tool calls and just emitted prose ending with *"Click Apply below to update the print format!"* with no Apply card attached.

Four independent root causes — all confirmed by direct file reads:

| # | Where | What |
|---|---|---|
| 1 | `lazychat_erpnext/desk_assistant/tools.py` — `commit_prepared_action` response builder (~line 4928) | Generic `link = f"/app/{frappe.scrub(doc.doctype)}/{doc.name}"` produces `print_format` (underscore). Frappe Desk routes use `print-format` (hyphen). Reports were special-cased in cycle-11; Print Format and the other typed wrappers were not. |
| 2 | `lazychat_erpnext/desk_assistant/tool_schemas.py` + system prompt in `claude_bridge.py` | Typed `prepare_create_*` wrappers don't pre-check for existing doc; no system-prompt rule telling the agent to pivot to `prepare_update_doc` on duplicate. Agent retries create until the turn ceiling. |
| 3 | `lazychat_erpnext/desk_assistant/tools.py:14` | `PREP_TTL_SEC = 300` (5 min). Multi-turn agent loops with retries blow past this. Error message is opaque — agent can't tell expired-token from wrong-user. |
| 4 | `lazychat_erpnext/desk_assistant/claude_bridge.py:13` (backend) + `apps/chat-ui/src/lib/agent.ts:709-714` (chat-ui) + system prompts | Default `MAX_TURNS = 8` is too tight; effort-medium gets 16 but the cascade of Bugs 1-3 burns through that budget. Final turn(s) emit prose without staging. No defensive chat-ui detection of this "ghost CTA" state. |

Source code at `tools.py:4823` (the preview `open_url`) ALREADY uses `print-format` (hyphen, correct). The chat-ui's "Open Print Format" button reads from the commit response's `link` field, not the preview's `open_url` — that's why the preview path works on first apply but the auto-open after `commit_prepared_action` hits the underscore URL.

---

## Architecture

Four targeted fixes, each independently shippable as a single commit inside `cycle-15`. Coordinated as one cycle because the user-visible symptom is one cascade. Backend-side: 3 of 4 fixes; chat-ui side: 1 of 4. No new files; no new dependencies; no doctype migrations.

```
[lazychat-erpnext/lazychat_erpnext/desk_assistant/]
├─ tools.py
│  ├─ NEW _doctype_url_slug(doctype: str) -> str         [Bug 1]
│  ├─ MOD commit_prepared_action: use _doctype_url_slug   [Bug 1]
│  ├─ MOD prepare_create_*: add exists-pre-check          [Bug 2]
│  ├─ MOD PREP_TTL_SEC: 300 → 1800                        [Bug 3]
│  └─ MOD _retrieve_action: distinguish expired vs wrong-user  [Bug 3]
├─ claude_bridge.py
│  ├─ MOD MAX_TURNS: 8 → 16                               [Bug 4]
│  └─ MOD _system_prompt: add CTA-must-have-tool rule + duplicate-pivot rule  [Bugs 2 + 4]
├─ tool_schemas.py
│  └─ MOD description of typed create wrappers: spell out duplicate handling  [Bug 2]
└─ scripts/smoke-test-tools.py
   └─ NEW T-cases for each bug                            [Bugs 1-4]

[lazychat.ai/apps/chat-ui/src/lib/]
├─ agentRunner.ts
│  └─ NEW final-turn ghost-CTA detection + inline warning render  [Bug 4]
└─ routerSystemPrompt.ts
   └─ MOD mirror the new CTA-must-have-tool + duplicate-pivot rules  [Bugs 2 + 4]
```

The two-phase mutation security boundary stays unchanged — none of these fixes weaken it.

---

## Section 1 — Bug 1: URL slug helper

### Root cause

`tools.py:~4928`, in `commit_prepared_action`'s response builder for typed-create actions, builds the post-commit link via:

```python
link = f"/app/{frappe.scrub(doc.doctype)}/{doc.name}"
```

`frappe.scrub("Print Format")` returns `print_format` (underscore-separated lowercase). Frappe Desk's router serves `/app/<doctype-slug>/<name>` where the slug is hyphen-separated lowercase. `frappe.scrub` is for module/field name normalization, NOT for URL slugs. The two conventions diverge for any multi-word doctype (`Print Format`, `Purchase Order`, `Sales Invoice`, `Stock Entry`, etc.).

Reports were special-cased in cycle-11 ("Query/Script Report URL routing fix") with hand-rolled `if/elif` branches for `Report Builder` / `Query Report` / `Script Report` → `/app/report/` or `/app/query-report/`. Print Format and all other multi-word doctypes were not.

### Fix

Add a helper at the top of `tools.py` (near `PREP_TTL_SEC`):

```python
def _doctype_url_slug(doctype: str) -> str:
    """Convert a DocType name to its Frappe Desk URL slug.

    Frappe Desk routes `/app/<slug>/<name>` where slug is the doctype
    name lowercased with spaces replaced by hyphens. This is distinct
    from `frappe.scrub()` (underscores, for module/field names).

    Examples:
        "Print Format" -> "print-format"
        "Purchase Order" -> "purchase-order"
        "Sales Invoice" -> "sales-invoice"
        "Report"        -> "report"
    """
    return (doctype or "").strip().lower().replace(" ", "-")
```

Replace every call site that builds a `/app/<slug>/...` URL to use this helper:

- `commit_prepared_action` response `link` (~line 4928) — replace `frappe.scrub(doc.doctype)` with `_doctype_url_slug(doc.doctype)`.
- `prepare_create_print_format` preview `open_url` (~line 4823) — already uses hyphenated literal; replace with `_doctype_url_slug("Print Format")` for consistency.
- Other preview `open_url` sites: search for `f"/app/` patterns in `tools.py` and update each one.
- Report's special-cased URL routing (`/app/query-report/` for Query/Script Reports, `/app/report/` for Report Builder) stays as-is — those are NOT covered by the slug helper (the routing prefix differs by report_type, not by doctype).

### Test

Add to `scripts/smoke-test-tools.py`:

- **T103a** — `_doctype_url_slug("Print Format") == "print-format"`.
- **T103b** — `_doctype_url_slug("Purchase Order") == "purchase-order"`.
- **T103c** — `_doctype_url_slug("Report") == "report"`.
- **T103d** — `_doctype_url_slug("")` returns `""` (graceful).
- **T103e** — Round-trip integration: stage `prepare_create_print_format(name="Lazychat Smoke PF", doc_type="Note")`, commit, assert the returned `link` field equals `/app/print-format/Lazychat Smoke PF` (URL-encoded by client; raw form is fine).

### Rollback

Single file change to `tools.py`. Revert the helper + revert call-site edits. No data migration. No schema change.

---

## Section 2 — Bug 2: Duplicate-create pivot

### Root cause

When a typed `prepare_create_*` wrapper (e.g. `prepare_create_print_format`, `prepare_create_report`, `prepare_create_workspace`) is called for a name that already exists, the wrapper proceeds to stage, the commit hits MariaDB's PRIMARY-key constraint, and returns:

```
IntegrityError(1062, "Duplicate entry 'Purchase Order - Agilitas' for key 'PRIMARY'")
```

The error is raw — no actionable hint pointing the agent toward `prepare_update_doc`. The agent's options are: (a) try the same create again with a different name, (b) try the same create again with the same name expecting a different outcome, or (c) give up. Haiku tends toward (b), burning turns.

Cycle "Block generic prepare_create_doc" (CLAUDE.md) added a TYPED-WRAPPER redirect for the generic `prepare_create_doc` path. Cycle "prepare_update_doc redirects to typed-create wrapper" added the reverse direction (update → create). The diagonal — `prepare_create_X` → `prepare_update_doc` on duplicate — is unhandled.

### Fix

Two layers:

**Layer 1 — Backend pre-check.** At the top of every typed `prepare_create_*` wrapper, before staging, check existence:

```python
# Inside prepare_create_print_format, before the existing logic
if frappe.db.exists("Print Format", pf_name):
    return {
        "ok": False,
        "error": f"Print Format '{pf_name}' already exists.",
        "hint": (
            f"To MODIFY the existing Print Format, use "
            f"prepare_update_doc(doctype='Print Format', name='{pf_name}', "
            f"patch={{...}}) on the next turn. If you want a DIFFERENT print "
            f"format, choose a name that doesn't exist (current: '{pf_name}')."
        ),
    }
```

Apply to: `prepare_create_print_format`, `prepare_create_report`, `prepare_create_workspace`, `prepare_create_kb`, `prepare_create_note`, `prepare_create_email_template`, `prepare_create_email_group`, `prepare_create_milestone_tracker`, `prepare_create_number_card`, `prepare_create_dashboard`, `prepare_create_scheduled_job`, `prepare_create_calendar_event`, `prepare_create_client_script`, `prepare_create_page`, `prepare_create_server_script` — every typed wrapper that has a known DocType + `name` field.

Wrappers that don't have a single deterministic `name` arg at the wrapper level (e.g. `prepare_create_custom_field` which uses `dt + fieldname` composite naming) get a similar check using their actual unique-key tuple.

**Layer 2 — System prompt rule.** Add to the TOOL-ERROR HONESTY block in `_system_prompt` (and mirror in `routerSystemPrompt.ts`):

```
DUPLICATE PIVOT — If a typed `prepare_create_X` returns 'already exists' OR a
commit produces IntegrityError 1062 (duplicate primary key), DO NOT retry the
same create. The doc exists already. Switch to `prepare_update_doc(doctype=...,
name=..., patch=...)` on the next turn to modify it. If the user explicitly
asked for a NEW doc, choose a different name that doesn't conflict.
```

### Test

- **T103f** — `prepare_create_print_format` with an existing name returns `ok: False`, `hint` mentions `prepare_update_doc`.
- **T103g** — same for `prepare_create_report` and `prepare_create_workspace` (one assertion per wrapper).
- **T103h** — pre-existence check is permission-aware (doesn't leak info about docs the user can't read).
- **T103i** — system-prompt-text smoke: assert `"DUPLICATE PIVOT"` appears verbatim in `_system_prompt(...)` output.

### Rollback

Per-wrapper revert; can be partial (e.g. revert only `prepare_create_print_format` if a wrapper trips on a non-name unique-key edge case). System prompt revert is one-line.

---

## Section 3 — Bug 3: Token TTL bump + clearer expired-token error

### Root cause

`tools.py:14`:

```python
PREP_TTL_SEC = 300
```

5 minutes was reasonable when the chat-ui used a "stage → user reads narration → user clicks Apply" flow with no agent retries between stage and commit. Multi-turn agent loops (Bugs 2 + 4 above) routinely take longer:

- Each agentic round-trip: 10-30s LLM latency + 1-10s tool dispatch + render.
- A 5-failure cascade: 5 × 30s = 2.5 min of LLM time alone.
- Add user pauses (reading the failure, deciding to retry): another 1-3 min.

By the time the agent finally stages a successful prep, the user might be 5+ min into the conversation. Commit fails with `"Token not found, expired, or not yours"` — opaque message that doesn't distinguish:
- Token expired (>5 min old) — agent should re-stage.
- Wrong user (token bound to a different session) — different bug, can't fix client-side.
- Already consumed (single-use; the agent or another tab already applied) — surface the prior result.

### Fix

Two changes in `tools.py`:

**Change 1 — TTL bump** (`tools.py:14`):

```python
PREP_TTL_SEC = 1800  # 30 minutes; was 300. Multi-turn agent loops blow past 5 min.
```

No security cost: tokens are still user-bound (the token cache key includes the user's email) and single-use (consumed on first successful commit). Longer TTL doesn't widen the attack surface.

**Change 2 — Distinguish expired vs missing in `_retrieve_action`** (~line 6222):

```python
def _retrieve_action(token: str) -> dict | None:
    """Return the staged action dict, or a structured error dict on miss."""
    if not token or len(token) < 8:
        return {"ok": False, "error": "Token malformed."}
    token_key = f"{PREP_KEY}{token}"
    obj = frappe.cache.get_value(token_key)
    if not obj:
        return {
            "ok": False,
            "error": (
                "Token not found — either it expired (TTL = 30 min) OR it was "
                "already consumed by a prior commit. Re-stage the action with a "
                "fresh prepare_* call and try Apply again."
            ),
        }
    if obj.get("user") != frappe.session.user:
        return {
            "ok": False,
            "error": (
                "Token belongs to a different user. Each preview_token is bound "
                "to the user who staged it. Re-stage with the current user."
            ),
        }
    return obj  # success path: the staged action
```

Caller (`commit_prepared_action`) reads `ok` flag the same as today.

### Test

- **T103j** — `PREP_TTL_SEC >= 1800`.
- **T103k** — `_retrieve_action("")` returns `ok: False, error contains "malformed"`.
- **T103l** — `_retrieve_action("nonexistent-token-xyz")` returns `ok: False, error contains "expired" or "consumed"`.
- **T103m** — stage as user A, attempt retrieve as user B (via `frappe.set_user`), assert returns `ok: False, error contains "different user"`.

### Rollback

Two-line revert. No persisted state change (existing tokens with 5-min TTL just expire normally; new tokens get 30-min TTL).

---

## Section 4 — Bug 4: Turn-budget bump + CTA-must-have-tool rule + chat-ui ghost-CTA detection

### Root cause

Three independent contributors:

1. **`claude_bridge.py:13`** `MAX_TURNS = 8` (backend hard cap). Effort=low maps to 8; medium=16; high=32; max=64. The default for backend-LLM path is 8.
2. **Agent emits "Click Apply" prose without staging** — when budget exhausts mid-action OR when the agent gets confused (e.g. by Bugs 1-3 cascade), it falls back to prose narration and terminates the turn without a `prepare_*` tool call. The chat-ui has no Apply card to render. User sees "Click Apply below" with no Apply button.
3. **No chat-ui detection** of the ghost-CTA state. User has to guess what to do next.

### Fix

Three layered changes:

**Change 1 — Default `MAX_TURNS` bump.** `claude_bridge.py:13`:

```python
MAX_TURNS = 16  # was 8. Aligns backend-LLM default with chat-ui's effort=medium.
```

Effort overrides still win: `EFFORT_MAP["low"]["max_turns"] = 8`, `["medium"] = 16`, etc. This change affects only callers that don't pass an effort kwarg (defensive fallback).

**Change 2 — CTA-must-have-tool rule in system prompt.** Append to TOOL-ERROR HONESTY:

```
NEVER emit text like "Click Apply" or "Click the Apply button" or "Apply
below" without an accompanying prepare_* tool call in the SAME turn. If
your last action FAILED and you cannot stage a fresh prepare_* this turn,
say "I need to re-stage — calling prepare_X now" and call it. Phantom CTAs
(text suggesting an Apply button when none exists) waste the user's time
and break trust.
```

Mirror in `routerSystemPrompt.ts` for the chat-ui browser-LLM path.

**Change 3 — Chat-ui defensive detection.** In `apps/chat-ui/src/lib/agentRunner.ts`, after the `done` message is appended:

```ts
// Bug 4 — ghost-CTA detection. If the final assistant message contains
// CTA-suggesting text but no prepare_* / mcpPreviewAction is attached to
// this conversation's most-recent assistant turn, surface a defensive
// warning so the user isn't waiting for an Apply card that will never come.
const finalText = doneMsg.text ?? "";
const ctaPattern = /\b(click\s+apply|apply\s+below|click\s+the\s+apply\s+button)\b/i;
const recentHasPreview = messages.slice(-6).some(
    (m) => m.kind === "mcpPreviewAction"
);
if (ctaPattern.test(finalText) && !recentHasPreview) {
    appendMessage(sid, {
        id: crypto.randomUUID(),
        kind: "error",
        role: "assistant",
        message: (
            "The agent ended the turn referencing an Apply button but did not "
            "stage an action. This usually means the agent ran out of turns "
            "or hit repeated failures. Try sending the request again, or "
            "switch to a stronger model (e.g. claude-sonnet-latest)."
        ),
        at: Date.now(),
    });
}
```

### Test

Backend:

- **T103n** — `MAX_TURNS >= 16` in `claude_bridge.py`.
- **T103o** — system-prompt-text smoke: assert `"NEVER emit text like \"Click Apply\""` appears verbatim in `_system_prompt(...)` output.

Chat-ui (vitest):

- **agentRunner.test.ts** new `describe('ghost-CTA detection')`:
  - Done message with "click Apply below" + no `mcpPreviewAction` in recent → `error` message appended with diagnostic copy.
  - Done message with "click Apply below" + `mcpPreviewAction` present → no error appended.
  - Done message WITHOUT CTA phrasing + no `mcpPreviewAction` → no error appended.

### Rollback

Three small reverts: 1-line `MAX_TURNS` (or change to 8 again), prompt block excision, chat-ui block excision + test removal. No data, no state migration.

---

## Sequencing

1. **Bug 1 (URL slug)** — backend only, single helper + 1-2 call-site edits. Smallest blast radius. Ship first.
2. **Bug 3 (TTL + error)** — backend only, ~5-line change. Ship second.
3. **Bug 2 (duplicate pivot)** — backend (wrapper pre-checks across ~15 wrappers) + system prompt + chat-ui prompt mirror. Ship third.
4. **Bug 4 (turn budget + CTA rule + chat-ui detection)** — backend prompt + chat-ui code + chat-ui vitest. Ship fourth.

Each is a separate commit inside `cycle-15`. Total ~4-6 hrs.

---

## Verification

### In-process smoke (must reach 283 → 283 + N pass / 0 fail / 6 skip)

Add T103a-T103o (15 new cases) per the per-section test specs. Existing 283/0/6 must stay green.

```bash
cp lazychat-erpnext/scripts/smoke-test-tools.py \
   <bench>/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd <bench>
bench --site erp.local execute lazychat_erpnext._smoke.run
# expected: === 298 pass, 0 fail, 6 skip ===
```

### HTTP-wire smoke (must stay 91/91)

No new tools, no schema changes → unchanged.

```bash
python3 lazychat-erpnext/test/curl_smoke.py
# expected: OK=80 | OK_ERROR=11
```

### Chat-ui vitest (must reach 461 → 461 + N pass / 0 fail)

Add `describe('ghost-CTA detection')` per Bug 4 spec. Existing tests stay green.

```bash
cd lazychat.ai
pnpm --filter chat-ui test
# expected: Test Files  78 passed (78), Tests  465 passed (465)
```

### End-to-end browser replay

Reproduce the user's exact transcript:

1. Restart bench after deploy (mtime cache-bust + Python import fresh).
2. Open `/app/purchase-order` in browser.
3. Open lazychat panel, model = `claude-haiku-latest`.
4. Upload `PO-M26-02-000400.pdf` (use any PO PDF available).
5. Send: *"Create Purchase Order Print format for purchase order doctype print format name- 'Purchase Order - Agilitas'"*.
6. Expected: agent stages successfully → Apply card → click Apply → **Open Print Format button navigates to `/app/print-format/Purchase Order - Agilitas`** (no 404).
7. Send: *"Add a header section with the company logo and address."*
8. Expected: agent calls `prepare_update_doc` (not duplicate create) → applies → no token expiry, no give-up text.

Capture before/after screenshots: `test/evidence/cycle-15-apply-path-hardening/`.

---

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| `_doctype_url_slug` produces wrong slug for doctypes with non-ASCII / special chars in the name | The Frappe core convention is ASCII-only doctype names; non-ASCII names break elsewhere anyway. If a real doctype with edge-case chars surfaces, add an explicit override map (e.g. `_DOCTYPE_SLUG_OVERRIDES = {"E-Way Bill": "e-way-bill"}`) — defer until needed. |
| `PREP_TTL_SEC = 1800` (30 min) increases Redis memory pressure | Each token's cache payload is ~5-50 KB. At 100 tokens/hour active load × 30 min TTL = ~50 concurrent tokens × 50 KB = 2.5 MB. Negligible. |
| Bumping `MAX_TURNS` to 16 increases per-conversation LLM cost | Effort-based mapping is unchanged; only the default fallback changes. Cycle-7's COMPLETENESS rule + Bug 4's CTA-must-have-tool rule reduce wasted turns, so net cost may DROP per successful flow. |
| `frappe.db.exists` pre-check in every typed wrapper adds 1 DB query per stage | Cheap (PRIMARY-key lookup; <1 ms). No measurable impact on stage latency. |
| Chat-ui ghost-CTA regex matches legitimate phrasing in a non-Apply context | Pattern is intentionally tight (`\b(click\s+apply|apply\s+below|click\s+the\s+apply\s+button)\b`). If false positives surface, refine to require both CTA phrasing AND tool-staging context. |

---

## Out of scope (deferred to next cycle)

- **Embeddings-based tool subsetting** (Path B from the earlier "support smaller models" question) — biggest product change for small-LLM reliability; needs its own cycle.
- **Print Format Jinja render-preview** — the agent's first 4 attempts failed Jinja validation (`Jinja template did not render: TypeError ...`). The render-preview validators added in cycle 13 cover Page HTML/JS/CSS but not Print Format Jinja. Adding Jinja preview would catch template errors at stage time before commit and reduce wasted turns. Separate scope.
- **Common `_check_exists_redirect_to_update(doctype, name, update_tool_name)` helper** used by all 19 mutation wrappers — would consolidate the per-wrapper pre-check into one place. Stop-gap is fine for cycle-15; refactor later.
- **TYPED-WRAPPER for `prepare_create_doc` on Print Format** — currently `prepare_create_doc(doctype="Print Format")` would be allowed (Print Format is in the typed-wrapper map per `_TYPED_WRAPPER_FOR_DOCTYPE`, but only if that map already includes it — verify and add if missing).
- **Smarter Plan-mode integration with the duplicate-pivot rule** — Plan mode emits a numbered plan first; the plan could include "If create fails with duplicate, switch to update." Out of scope here.

---

## Success criteria

After cycle-15 deploys, a fresh repeat of the user's exact transcript should:

1. Successfully stage the Print Format on the first or second attempt (depends on Jinja template — out of scope to fix Jinja, in scope to fix the URL after Apply).
2. Clicking "Open Print Format" navigates to the rendered Print Format page in Desk (200, not 404).
3. Asking for an enhancement triggers `prepare_update_doc` on the existing Print Format (not duplicate `prepare_create_print_format`).
4. The enhancement Apply card renders within token TTL (no expired-token error in a reasonable multi-turn loop).
5. If the agent ever gives up emitting Apply cards, the user sees an inline error explaining what happened — not silent ghost-CTA text.
