# Terms of Use — LazyChat (`lazychat_erpnext`)

_Last updated: 2026-05-12_

This is a plain-language summary of the terms under which the **LazyChat**
Frappe app (`lazychat_erpnext`, the "App") is made available. It is not a
formal contract drafted by a lawyer; if you need one for your organization,
have your counsel review it.

## 1. What the App is

LazyChat is **open-source software** distributed under the MIT License (see
[`LICENSE`](LICENSE)). It installs into an ERPNext / Frappe bench you operate
(self-hosted or on Frappe Cloud) and adds an AI assistant to the Desk plus an
MCP server exposing permission-scoped tools.

The author and publisher of the App (Soumya Sethy) provides the **source code
only**. There is no hosted service, no backend run by the publisher, and no
account you sign up for with the publisher.

## 2. "As-is", no warranty

The App is provided **"AS IS", without warranty of any kind**, express or
implied, including but not limited to merchantability, fitness for a particular
purpose, and non-infringement. To the maximum extent permitted by law, the
publisher and contributors are **not liable** for any claim, damages, data
loss, or other liability arising from the App or its use — including any
actions the AI assistant takes against your data. This mirrors the MIT License
under which the App is licensed.

## 3. Your responsibilities

By installing and using the App you agree that:

- **You operate it.** You are responsible for installing, configuring,
  securing, backing up, and maintaining your own bench and site, and for any
  changes the App (or its AI assistant) makes to your data.
- **Bring your own LLM.** The App does not include an LLM. You supply your own
  API key for a model provider (e.g. Anthropic, OpenAI, OpenRouter, NVIDIA,
  Together, Groq, or any OpenAI-compatible / local endpoint). Your use of that
  provider is governed by **their** terms and pricing — not these terms. You
  are responsible for the cost of those API calls.
- **Permissions matter.** The App's tools run with the permissions of the
  logged-in Frappe user. Anything that user can read or write, the assistant
  can be asked to read or write. State-changing operations are gated (the LLM
  stages a `prepare_*` action; a human clicks Apply / `/commit`), but you are
  responsible for who you grant access to and how you configure the gates
  (`allow_email`, `allow_dangerous_tools`, etc.).
- **Lawful use.** You will not use the App to violate applicable laws, infringe
  others' rights, or process data you are not authorized to process.

## 4. Support

Support is **best-effort and community-based** via the project's GitHub issue
tracker: <https://github.com/soumyasethy/lazychat-erpnext/issues>. There is no
service-level agreement, uptime guarantee, or commitment to fix any particular
issue or release on any schedule.

## 5. Changes

The App evolves; features may change or be removed between releases. These
terms may also be updated — the version in the repository's `main` branch is
the current one. Continued use of the App after a change constitutes acceptance
of the updated terms.

## 6. Contact

Soumya Sethy — sethy.soumyaranjan@gmail.com — <https://github.com/soumyasethy/lazychat-erpnext>
