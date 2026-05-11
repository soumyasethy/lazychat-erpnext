# Contributing

Thanks for considering a contribution. This project ships ERPNext consultants and developers a chat-driven control panel; the bar is high on permission scoping, audit safety, and the no-hallucinated-success rule.

## Quick facts

- **Stack** — Frappe v15 / Python 3.11 / React + Vite chat-ui (sibling repo `lazychat.ai/`).
- **Branching** — Feature branches as `cycle-<n>-<short-name>` (e.g. `cycle-13-readme-rewrite`). Cycles roughly map to milestones; tags follow the same pattern.
- **Commits** — [Conventional Commits](https://www.conventionalcommits.org/): `feat(scope): …`, `fix(…)`, `chore(…)`, `test(…)`, `docs(…)`. Keep them small and focused. **Never** include `Co-Authored-By: Claude` (or any AI co-author) — explicit project policy.
- **Pushes** — Owners (or anyone with write) push directly. PRs are required for non-trivial work; force-push to `main` is allowed only with explicit owner approval.

## Before you open a PR

Both gates must be green:

```bash
# 1) In-process smoke (in your bench)
cp lazychat-erpnext/scripts/smoke-test-tools.py \
   <bench>/apps/lazychat_erpnext/lazychat_erpnext/_smoke.py
cd <bench>
bench --site <site> execute lazychat_erpnext._smoke.run
# expected last line: === N pass, 0 fail, X skip ===

# 2) HTTP-wire smoke (from the repo root)
python3 lazychat-erpnext/test/curl_smoke.py
# expected last line: tools registered: 94, called: 94
```

If you add a new tool: also add a T## case in `scripts/smoke-test-tools.py` AND a validator entry in `test/tool_args.py`. The smoke harness exists to catch drift between schema, implementation, and live behavior — please do not skip it.

## Code conventions

- **TAB indentation** in `desk_assistant/*.py` (matches Frappe convention).
- **Permission scoping** — every tool calls `frappe.has_permission(...)` BEFORE any DB access, and re-checks at commit time. No god-mode.
- **Two-phase mutations** — every state-changing tool MUST be `prepare_<verb>` + a corresponding `commit_prepared` handler. The LLM never gets a direct write tool.
- **Tool errors return `{"error": "human-readable message"}`** — not exceptions. The agent loop reads `error` and apologizes / retries. Treat the error message as user-facing.
- **Tool registry size** — `tool_schemas.py:TOOL_SCHEMAS` is the source of truth (currently 94). T54 in the smoke pins live count to `len(TOOL_SCHEMAS)`. Don't hardcode the number elsewhere.

## Adding a new tool — checklist

1. Implementation in `tools.py` with permission check + try/except.
2. Schema in `tool_schemas.py` (this is what the LLM reads — write it like a great function docstring).
3. If mutating: commit handler in `commit_prepared`.
4. Mention in the system prompt (`claude_bridge.py:_system_prompt`) if the tool needs nudging to be picked up.
5. T## smoke case + `tool_args.py` validator.
6. Re-run both smoke gates.
7. Open PR — link to the smoke output and a screenshot if the tool is user-facing.

## Discussions / bugs

- **Bug reports** — open a GitHub Issue with the smoke output, the failing transcript (paste from the chat panel), and your bench / Frappe / ERPNext versions.
- **Feature requests** — describe the user workflow first ("As an ERPNext consultant, I want to…") before suggesting tool shapes.

By contributing, you agree your contributions will be licensed under the MIT License (see [LICENSE](LICENSE)).
