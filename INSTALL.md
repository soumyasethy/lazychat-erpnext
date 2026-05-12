# Installing LazyChat (`lazychat_erpnext`)

> **On Frappe Cloud?** Install it in one click from the marketplace — you don't need any of the commands below.

## Quick install (self-hosted bench)

```bash
cd /path/to/your/frappe-bench
bench get-app https://github.com/soumyasethy/lazychat-erpnext --branch main
bench --site <your-site> install-app lazychat_erpnext
bench restart   # then open /app and look for the chat icon (right edge)
```

After install, the app seeds disabled-by-default LLM Provider rows (OpenAI, Anthropic, NVIDIA, OpenRouter, Vercel AI, LM Studio) — enable one and add your API key from `/app/llm-provider`. Or skip server-side config entirely and let users bring their own keys via the chat-ui's model picker (browser-LLM path).

## Setup options

### Option A — release branch (zero local build)

For the panel up in 60 seconds with no `pnpm` / `npm` / chat-ui build chain — the `release` branch ships the bundled `public/lazychat_dist/` directly:

```bash
cd /path/to/your/frappe-bench
bench get-app https://github.com/soumyasethy/lazychat-erpnext --branch release
bench --site <your-site> install-app lazychat_erpnext
bench restart
```

### Option B — build from source

If you want to customize the chat-ui, develop a new tool, or run HMR while editing React:

```bash
git clone https://github.com/soumyasethy/lazychat.ai.git
git clone https://github.com/soumyasethy/lazychat-erpnext.git

# Build the chat-ui dist into the Frappe app's public dir
./lazychat-erpnext/scripts/build-lazychat-dist.sh

# Deploy to a bench
BENCH_ROOT=/path/to/frappe-bench DEPLOY_SITE=erp.local \
  ./lazychat-erpnext/scripts/deploy-local.sh

cd /path/to/frappe-bench
bench get-app file:///absolute/path/to/lazychat-erpnext
bench --site erp.local install-app lazychat_erpnext
```

### Option C — HMR dev (chat-ui + Frappe side-by-side)

Edit React `.tsx` files and watch the panel reload instantly:

```bash
# Point the iframe src at your local Vite server
bench --site erp.local execute frappe.db.set_value \
  --kwargs '{"dt":"Lazychat Settings","dn":"Lazychat Settings","field":"iframe_base_url","val":"http://127.0.0.1:5173"}'

# Run Vite + bench in parallel — see the umbrella repo's dev.sh
sh dev.sh
```

## Configuration

See the **Configuration** section of the [README](README.md) — all settings live in the `Lazychat Settings` doctype (`/app/lazychat-settings`) and in the chat-ui's in-app Server Config dialog.
