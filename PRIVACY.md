# Privacy Policy — LazyChat (`lazychat_erpnext`)

_Last updated: 2026-05-12_

**Short version:** LazyChat is open-source software that runs entirely inside
**your** ERPNext / Frappe bench. The publisher of this app (Soumya Sethy)
operates no servers, receives no telemetry, and has no access to your data,
your API keys, or your conversations. The App does not "phone home."

This is a plain-language summary, not a formal legal document.

## 1. Who this covers

This policy describes the data behaviour of the **LazyChat Frappe app**
(`lazychat_erpnext`) itself. It does **not** cover:

- **The LLM provider you choose** (Anthropic, OpenAI, OpenRouter, NVIDIA,
  Together, Groq, a local model, etc.) — when you send a message, the App
  forwards your prompt and the relevant tool results to that provider. Their
  privacy policy and data-handling terms apply to that data. Choose a provider
  whose terms you're comfortable with.
- **Your hosting** — if you run on Frappe Cloud or any managed host, that
  provider's privacy policy applies to your site.
- **GitHub** — if you open an issue or PR on the project, GitHub's privacy
  policy applies to what you post there.

## 2. What data flows where

```
your browser  ⟷  your ERPNext/Frappe site  ⟷  the LLM provider YOU configured
```

The publisher of this app is **not** in that path. There is no LazyChat-operated
backend.

- **Backend-LLM mode:** the API key is stored, encrypted, in the `LLM Provider`
  doctype in **your** database. Prompts/results go from your bench to the
  provider's API.
- **Browser-LLM (bring-your-own-key) mode:** the API key lives in **your
  browser's** `localStorage` and is sent only to the provider endpoint you
  point it at. It is never sent to the publisher.

## 3. What the App stores — and where

Everything the App stores lives in **your own Frappe database**, under your
control. Nothing is sent off your infrastructure except to the LLM provider you
pick. The App creates these records:

| Stored | Where | What it is |
|---|---|---|
| Conversation history | `Claude Conversation` doctype | Your chat turns, so you can resume sessions |
| Token / cost usage | `Lazychat Usage Log` doctype | Per-turn model name + token counts + estimated cost, for your own visibility |
| Knowledge-base content & embeddings | `Lazychat Knowledge Base` / `Lazychat KB Chunk` doctypes | Only files you explicitly attach to a KB |
| LLM provider/model config | `LLM Provider` / `LLM Model` doctypes | Endpoints, model IDs, and your (encrypted) API keys |
| Settings | `Lazychat Settings` doctype | Feature toggles you set |

You can inspect, export, or delete any of these via the Frappe Desk like any
other doctype. Uninstalling the app removes these doctypes and their data.

## 4. Telemetry / analytics

**None.** The App does not collect usage analytics, crash reports, or any other
data and does not transmit anything to the publisher or any third party other
than the LLM provider you configure (and only the content you send through the
assistant).

## 5. Permissions

The App's tools execute with the permissions of the logged-in Frappe user — it
cannot read or write anything that user couldn't already access in ERPNext.
Whatever data that user can see, the assistant can be asked to summarize or act
on (subject to the Apply / `/commit` confirmation gate for any write). Manage
access the same way you manage any ERPNext user.

## 6. Changes

This policy may be updated; the version in the repository's `main` branch is
the current one.

## 7. Contact

Soumya Sethy — sethy.soumyaranjan@gmail.com — <https://github.com/soumyasethy/lazychat-erpnext>
