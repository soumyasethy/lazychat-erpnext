# Multi-Provider Extension — Any LLM via OpenRouter / Vercel / NVIDIA / OpenAI / Anthropic

Follow-up to `erpnext_claude_mcp_build_guide.md`. This drops in:

- A **model picker** in the chat header (and per-conversation memory).
- Two new doctypes — **LLM Provider** and **LLM Model** — so adding a new gateway is data, not code.
- A **provider adapter layer** with two adapters: `anthropic` (native) and `openai_compatible` (covers OpenAI, OpenRouter, NVIDIA NIM, Vercel AI Gateway, LM Studio, Groq, Together, Fireworks, Anyscale, and any other OpenAI-shaped endpoint).
- Translation of **tool calls and tool results** between Anthropic and OpenAI formats so the rest of the agentic loop is provider-agnostic.

---

## 1. Why two adapters cover everything

| Provider | API style | base_url example | model_id example |
|---|---|---|---|
| Anthropic (direct) | Anthropic Messages | `https://api.anthropic.com/v1` | `claude-sonnet-4-6` |
| OpenAI | OpenAI Chat Completions | `https://api.openai.com/v1` | `gpt-4o` |
| OpenRouter | OpenAI-compatible | `https://openrouter.ai/api/v1` | `anthropic/claude-sonnet-4-6`, `meta-llama/llama-3.1-70b-instruct` |
| NVIDIA NIM | OpenAI-compatible | `https://integrate.api.nvidia.com/v1` | `meta/llama-3.1-70b-instruct`, `nvidia/llama-3.1-nemotron-70b-instruct` |
| Vercel AI Gateway | OpenAI-compatible | `https://ai-gateway.vercel.sh/v1` (verify in your Vercel dashboard) | `anthropic/claude-sonnet-4-6` |
| LM Studio (local) | OpenAI-compatible | `http://localhost:1234/v1` | whatever LM Studio shows |
| Ollama | OpenAI-compatible | `http://localhost:11434/v1` | `llama3.1`, `qwen2.5` |
| Groq | OpenAI-compatible | `https://api.groq.com/openai/v1` | `llama-3.1-70b-versatile` |
| Together | OpenAI-compatible | `https://api.together.xyz/v1` | `meta-llama/Llama-3.1-70B-Instruct-Turbo` |

Two adapters. Everything else is configuration.

> The exact base URL for Vercel AI Gateway can change as the product evolves — keep `base_url` as user-configurable data so you don't have to ship a release every time something shifts.

---

## 2. New doctypes

### `LLM Provider` (List)
| Fieldname | Type | Notes |
|---|---|---|
| provider_name | Data, unique | "Anthropic", "OpenRouter Prod", "Local LM Studio" |
| provider_type | Select | `anthropic`, `openai_compatible` |
| base_url | Data | no trailing slash |
| api_key | Password | encrypted |
| extra_headers | Code (JSON) | optional, e.g. `{"HTTP-Referer": "https://erp.acme.com", "X-Title": "ERPNext"}` for OpenRouter analytics |
| enabled | Check | |

### `LLM Model` (List)
| Fieldname | Type | Notes |
|---|---|---|
| model_label | Data | what the user sees in the dropdown ("Claude Sonnet 4.6 via Anthropic") |
| provider | Link → LLM Provider | |
| model_id | Data | wire identifier sent to the provider |
| supports_tools | Check | turn off for models without tool use → bridge will downgrade gracefully |
| max_output_tokens | Int | default 4096 |
| context_window | Int | informational |
| input_price_per_mtok | Float | $/M input tokens — used by usage tracking |
| output_price_per_mtok | Float | $/M output tokens |
| is_default | Check | one global default |
| enabled | Check | |

### Seed fixtures (`fixtures/llm_provider.json`, `fixtures/llm_model.json`)

Ship sensible defaults so install gives users something to click immediately:

```json
[
  {"doctype":"LLM Provider","provider_name":"Anthropic","provider_type":"anthropic","base_url":"https://api.anthropic.com/v1","enabled":1},
  {"doctype":"LLM Provider","provider_name":"OpenAI","provider_type":"openai_compatible","base_url":"https://api.openai.com/v1","enabled":0},
  {"doctype":"LLM Provider","provider_name":"OpenRouter","provider_type":"openai_compatible","base_url":"https://openrouter.ai/api/v1","enabled":0},
  {"doctype":"LLM Provider","provider_name":"NVIDIA","provider_type":"openai_compatible","base_url":"https://integrate.api.nvidia.com/v1","enabled":0},
  {"doctype":"LLM Provider","provider_name":"Vercel AI Gateway","provider_type":"openai_compatible","base_url":"https://ai-gateway.vercel.sh/v1","enabled":0},
  {"doctype":"LLM Provider","provider_name":"LM Studio (local)","provider_type":"openai_compatible","base_url":"http://localhost:1234/v1","enabled":0}
]
```

API keys stay empty in fixtures — the user fills them via the form so they're encrypted at rest.

---

## 3. The adapter layer

A clean shape: every adapter takes the same internal canonical format (which mirrors Anthropic's, since that's already what your loop speaks) and returns the same shape. The OpenAI adapter does the translation; everything else stays untouched.

```
lazychat_erpnext/
└── providers/
    ├── __init__.py
    ├── base.py
    ├── anthropic.py
    └── openai_compat.py
```

### `providers/base.py`

```python
"""
Internal canonical types — mirror Anthropic's Messages API shape because
that's what the agentic loop already speaks.

Message shape (list[dict]):
  {"role": "user"|"assistant",
   "content": [
     {"type":"text", "text": "..."},
     {"type":"tool_use", "id":"tu_x", "name":"get_list", "input":{...}},
     {"type":"tool_result", "tool_use_id":"tu_x", "content":"..."}
   ]}

Tool schema: Anthropic-shaped {name, description, input_schema}.
"""
from dataclasses import dataclass
from typing import Any

@dataclass
class AdapterResponse:
    content: list[dict]            # canonical content blocks (text + tool_use)
    stop_reason: str               # "end_turn" | "tool_use" | "max_tokens" | other
    usage: dict[str, Any]          # {"input_tokens":..., "output_tokens":...}

class BaseAdapter:
    def chat(self, *, provider, model, messages, system, tools, max_tokens) -> AdapterResponse:
        raise NotImplementedError
```

### `providers/anthropic.py`

```python
import requests
from .base import BaseAdapter, AdapterResponse

class AnthropicAdapter(BaseAdapter):
    def chat(self, *, provider, model, messages, system, tools, max_tokens):
        headers = {
            "x-api-key": provider.get_password("api_key"),
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if provider.extra_headers:
            import json as _json
            headers.update(_json.loads(provider.extra_headers))

        body = {
            "model": model.model_id,
            "max_tokens": max_tokens or model.max_output_tokens or 4096,
            "system": system,
            "messages": messages,
        }
        if tools and model.supports_tools:
            body["tools"] = tools

        r = requests.post(f"{provider.base_url}/messages", headers=headers, json=body, timeout=120)
        r.raise_for_status()
        data = r.json()
        return AdapterResponse(
            content=data["content"],
            stop_reason=data.get("stop_reason", "end_turn"),
            usage=data.get("usage", {}),
        )
```

### `providers/openai_compat.py`

This is the heavy lifter — translates both directions.

```python
import json
import requests
from .base import BaseAdapter, AdapterResponse

class OpenAICompatAdapter(BaseAdapter):
    def chat(self, *, provider, model, messages, system, tools, max_tokens):
        oai_messages = self._to_oai_messages(system, messages)
        oai_tools = self._to_oai_tools(tools) if tools and model.supports_tools else None

        headers = {
            "Authorization": f"Bearer {provider.get_password('api_key')}",
            "Content-Type": "application/json",
        }
        if provider.extra_headers:
            headers.update(json.loads(provider.extra_headers))

        body = {
            "model": model.model_id,
            "messages": oai_messages,
            "max_tokens": max_tokens or model.max_output_tokens or 4096,
        }
        if oai_tools:
            body["tools"] = oai_tools
            body["tool_choice"] = "auto"

        r = requests.post(f"{provider.base_url}/chat/completions",
                          headers=headers, json=body, timeout=120)
        r.raise_for_status()
        data = r.json()
        choice = data["choices"][0]
        msg = choice["message"]
        finish = choice.get("finish_reason", "stop")

        content_blocks = self._from_oai_message(msg)
        stop_reason = "tool_use" if finish == "tool_calls" else (
            "max_tokens" if finish == "length" else "end_turn"
        )
        usage = data.get("usage", {})
        return AdapterResponse(
            content=content_blocks,
            stop_reason=stop_reason,
            usage={
                "input_tokens": usage.get("prompt_tokens", 0),
                "output_tokens": usage.get("completion_tokens", 0),
            },
        )

    # ---- request translation: canonical → OpenAI ------------------------
    @staticmethod
    def _to_oai_messages(system, messages):
        out = []
        if system:
            out.append({"role": "system", "content": system})
        for m in messages:
            role = m["role"]
            content = m["content"]

            # User messages can carry tool_result blocks; OpenAI splits these out.
            if role == "user" and isinstance(content, list):
                text_parts, tool_results = [], []
                for b in content:
                    if b.get("type") == "tool_result":
                        tool_results.append(b)
                    elif b.get("type") == "text":
                        text_parts.append(b["text"])
                # Tool results become separate role:"tool" messages
                for tr in tool_results:
                    out.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": tr["content"] if isinstance(tr["content"], str)
                                   else json.dumps(tr["content"]),
                    })
                if text_parts:
                    out.append({"role": "user", "content": "\n".join(text_parts)})
                continue

            if role == "user":  # plain string
                out.append({"role": "user", "content": content})
                continue

            # Assistant messages: split text + tool_use into one OAI message
            if role == "assistant" and isinstance(content, list):
                text_parts, tool_calls = [], []
                for b in content:
                    if b.get("type") == "text":
                        text_parts.append(b["text"])
                    elif b.get("type") == "tool_use":
                        tool_calls.append({
                            "id": b["id"],
                            "type": "function",
                            "function": {
                                "name": b["name"],
                                "arguments": json.dumps(b["input"] or {}),
                            },
                        })
                oai_msg = {"role": "assistant"}
                oai_msg["content"] = "\n".join(text_parts) if text_parts else None
                if tool_calls:
                    oai_msg["tool_calls"] = tool_calls
                out.append(oai_msg)
                continue

            out.append({"role": role, "content": content})
        return out

    @staticmethod
    def _to_oai_tools(tools):
        return [{
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t["input_schema"],
            },
        } for t in tools]

    # ---- response translation: OpenAI → canonical -----------------------
    @staticmethod
    def _from_oai_message(msg):
        blocks = []
        text = msg.get("content")
        if text:
            blocks.append({"type": "text", "text": text})
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc["function"]["arguments"]}
            blocks.append({
                "type": "tool_use",
                "id": tc["id"],
                "name": tc["function"]["name"],
                "input": args,
            })
        return blocks
```

### `providers/__init__.py`

```python
import frappe
from .anthropic import AnthropicAdapter
from .openai_compat import OpenAICompatAdapter

_REGISTRY = {
    "anthropic": AnthropicAdapter(),
    "openai_compatible": OpenAICompatAdapter(),
}

def get_adapter(provider_type):
    if provider_type not in _REGISTRY:
        frappe.throw(f"No adapter for provider_type={provider_type}")
    return _REGISTRY[provider_type]

def resolve_model(model_label=None):
    """Return (model_doc, provider_doc, adapter)."""
    if model_label:
        model = frappe.get_doc("LLM Model", {"model_label": model_label, "enabled": 1})
    else:
        model = frappe.get_doc("LLM Model", {"is_default": 1, "enabled": 1})
    provider = frappe.get_doc("LLM Provider", model.provider)
    if not provider.enabled:
        frappe.throw(f"Provider {provider.provider_name} is disabled")
    return model, provider, get_adapter(provider.provider_type)
```

---

## 4. Updated bridge

Replace the `run_agentic_turn` body in `claude_bridge.py` (§6 of the main guide):

```python
import json
import frappe
from .tool_schemas import TOOL_SCHEMAS
from .tools import execute_tool
from .providers import resolve_model

MAX_TURNS = 8

def _system_prompt(context):
    # unchanged from main guide — see §6
    ...

def run_agentic_turn(user_message, history, context, *,
                     model_label=None, allow_writes=False, emit=None):
    model, provider, adapter = resolve_model(model_label)
    history = list(history) + [{"role": "user", "content": user_message}]
    usage_total = {"input_tokens": 0, "output_tokens": 0}

    for _turn in range(MAX_TURNS):
        resp = adapter.chat(
            provider=provider,
            model=model,
            messages=history,
            system=_system_prompt(context),
            tools=TOOL_SCHEMAS,
            max_tokens=model.max_output_tokens or 4096,
        )
        usage_total["input_tokens"] += resp.usage.get("input_tokens", 0)
        usage_total["output_tokens"] += resp.usage.get("output_tokens", 0)

        history.append({"role": "assistant", "content": resp.content})

        tool_uses = []
        for block in resp.content:
            if block["type"] == "text" and emit:
                emit({"type": "text_delta", "delta": block["text"]})
            elif block["type"] == "tool_use":
                tool_uses.append(block)
                if emit:
                    emit({"type": "tool_use", "id": block["id"],
                          "name": block["name"], "input": block["input"]})

        if resp.stop_reason != "tool_use" or not tool_uses:
            break

        tool_results = []
        for tu in tool_uses:
            result = execute_tool(tu["name"], tu["input"], allow_writes=allow_writes)
            if emit:
                emit({"type": "tool_result", "name": tu["name"], "result": result})
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu["id"],
                "content": json.dumps(result, default=str)[:50000],
            })
        history.append({"role": "user", "content": tool_results})

    if emit:
        emit({"type": "usage", "model": model.model_label, **usage_total,
              "cost_estimate": _estimate_cost(model, usage_total)})
    return history, usage_total

def _estimate_cost(model, usage):
    in_cost = (usage["input_tokens"] / 1_000_000) * (model.input_price_per_mtok or 0)
    out_cost = (usage["output_tokens"] / 1_000_000) * (model.output_price_per_mtok or 0)
    return round(in_cost + out_cost, 6)
```

The rest of the agentic loop is provider-agnostic now.

---

## 5. Updated `api.py`

```python
@frappe.whitelist()
def chat_stream(message, conversation_id=None, context=None,
                model_label=None, confirmed_writes=False):
    if isinstance(context, str):
        context = json.loads(context)
    # ... persist conversation as before ...
    new_history, usage = run_agentic_turn(
        message, history, context or {},
        model_label=model_label,
        allow_writes=bool(confirmed_writes),
        emit=emit,
    )
    convo.history = json.dumps(new_history, default=str)
    convo.last_model = model_label
    convo.total_input_tokens = (convo.total_input_tokens or 0) + usage["input_tokens"]
    convo.total_output_tokens = (convo.total_output_tokens or 0) + usage["output_tokens"]
    convo.save(ignore_permissions=True)
    ...

@frappe.whitelist(allow_guest=False)
def list_models():
    """Powers the model dropdown in the chat header."""
    rows = frappe.get_all(
        "LLM Model",
        filters={"enabled": 1},
        fields=["name", "model_label", "model_id", "provider",
                "supports_tools", "is_default"],
        order_by="is_default desc, model_label asc",
    )
    # Filter out models whose provider is disabled or has no key
    out = []
    for r in rows:
        prov = frappe.get_cached_doc("LLM Provider", r["provider"])
        if not prov.enabled:
            continue
        try:
            if not prov.get_password("api_key") and prov.provider_type != "openai_compatible":
                # local providers can be keyless
                if "localhost" not in prov.base_url and "127.0.0.1" not in prov.base_url:
                    continue
        except Exception:
            continue
        r["provider_name"] = prov.provider_name
        out.append(r)
    return out
```

Add fields on `Claude Conversation` while you're there: `last_model` (Data), `total_input_tokens` (Int), `total_output_tokens` (Int).

---

## 6. UI — model picker in the chat header

Patch `public/js/chat_widget.js` from §3 of the main guide. Two changes: a header dropdown, and pass `model_label` on every send.

### Inside the shadow DOM template, replace the `<div class="header">` block:

```html
<div class="header">
  <div style="flex:1; min-width:0">
    <h3>Lazychat MCP ERPNext</h3>
    <div class="ctx" id="ctx"></div>
  </div>
  <select id="model-picker"
          style="background:#2d1f5a;color:#fff;border:1px solid #4a3a7a;border-radius:6px;
                 padding:4px 8px;font-size:11px;max-width:160px;margin-right:8px;cursor:pointer">
    <option>Loading…</option>
  </select>
  <button id="close" style="background:none;border:none;color:#fff;font-size:18px;cursor:pointer">×</button>
</div>
```

### Add this initialisation after the `$ = ...` helpers:

```js
const modelPicker = $("#model-picker");
const STORAGE_KEY = "lazychat_erpnext_model";
let selectedModel = localStorage.getItem(STORAGE_KEY) || null;

async function loadModels() {
  try {
    const r = await fetch("/api/method/lazychat_erpnext.api.list_models", {
      headers: { "X-Frappe-CSRF-Token": frappe.csrf_token },
    });
    const data = await r.json();
    const models = data.message || [];
    if (!models.length) {
      modelPicker.innerHTML = '<option>No models configured</option>';
      modelPicker.disabled = true;
      return;
    }
    modelPicker.innerHTML = models
      .map((m) => {
        const sel = (selectedModel === m.model_label) ||
                    (!selectedModel && m.is_default) ? "selected" : "";
        const tools = m.supports_tools ? "🔧" : "";
        return `<option value="${escapeHtml(m.model_label)}" ${sel}>
                  ${tools} ${escapeHtml(m.model_label)}
                </option>`;
      })
      .join("");
    if (!selectedModel) selectedModel = modelPicker.value;
  } catch (e) {
    modelPicker.innerHTML = '<option>Error loading</option>';
  }
}
modelPicker.addEventListener("change", () => {
  selectedModel = modelPicker.value;
  localStorage.setItem(STORAGE_KEY, selectedModel);
  append("tool", `Switched to ${selectedModel}`,
         { collapsible: false, summary: "" });
});
loadModels();
```

### In the `send()` body, add `model_label` to the request:

```js
body: JSON.stringify({
  message: text,
  conversation_id: conversationId,
  context: currentContext(),
  model_label: selectedModel,
}),
```

### Show usage on the `usage` event:

```js
} else if (evt.type === "usage") {
  const cost = evt.cost_estimate ? ` · $${evt.cost_estimate.toFixed(4)}` : "";
  append("tool",
         `${evt.model} · ${evt.input_tokens} in / ${evt.output_tokens} out${cost}`,
         { collapsible: false, summary: "" });
}
```

Now the user can flip between Claude on Anthropic, Llama on NVIDIA, GPT-4o on OpenAI, and a local Qwen on LM Studio without leaving the chat.

---

## 7. Tool-use compatibility — what to do when models can't

Reality check: not every model on every provider supports tool use cleanly. Llama on NVIDIA NIM does, but some smaller open models don't, and quality of tool-call adherence varies wildly.

The `supports_tools` flag on `LLM Model` is the switch. When it's off, the bridge should:

1. **Don't pass `tools=`** to the adapter (already handled).
2. **Inline a tool description into the system prompt** so the model can at least *suggest* what tool to run, even if it can't structure a call.
3. **Use a "manual mode"** — the assistant returns a JSON object the bridge parses and executes. Add this prompt fragment when `supports_tools=False`:

```python
TOOLLESS_PROMPT_SUFFIX = """
You don't have native tool use. When you need data, respond with EXACTLY:
<tool>{"name": "tool_name", "input": {...}}</tool>
…and nothing else. The system will execute the tool and re-prompt you with the result.
Available tools:
""" + "\n".join(f"- {t['name']}: {t['description']}" for t in TOOL_SCHEMAS)
```

Then in the bridge, when `supports_tools=False`, parse the assistant's last text block for `<tool>...</tool>`, dispatch the same way, and feed the result back as a regular user message.

This is a fallback worth shipping but the experience is markedly worse — for production traffic, prefer providers/models with native tool use (any Claude, GPT-4-class, Llama 3.1+, Mistral Large, Qwen 2.5+).

---

## 8. Streaming with mixed providers

Both APIs do SSE, but the event shape differs. If you want true token-level streaming across providers, extend each adapter with a `stream_chat()` that yields canonical events:

```python
# providers/base.py
def stream_chat(self, ...) -> Iterator[dict]:
    """Yields events: {'type':'text_delta','delta':...},
                      {'type':'tool_use_start','id':...,'name':...},
                      {'type':'tool_use_input_delta','id':...,'partial_json':...},
                      {'type':'message_stop','stop_reason':...,'usage':...}"""
```

- **Anthropic**: parse `content_block_start` / `content_block_delta` / `message_delta` events.
- **OpenAI-compatible**: parse `choices[0].delta.content` (text), `choices[0].delta.tool_calls[].function.arguments` (partial JSON for tool input — accumulate per `index`), and the final `usage` event when `stream_options.include_usage=true`.

OpenAI tool-call streaming has a gotcha: argument JSON arrives in fragments and you have to assemble them by `index` before firing a single canonical `tool_use` event downstream. Keep the assembly in the adapter so the bridge stays clean.

If it sounds like a lot of plumbing for diminishing returns — it is. The non-streaming path you already have is fine for ERPNext-internal use; stream only the final assistant text and let tool calls land atomically. Users care more about *seeing tool calls happen* than seeing JSON characters arrive one by one.

---

## 9. The MCP server, briefly

Nothing changes in §9 of the main guide — the MCP server is a *read-side* exposing ERPNext to external Claude clients. It's independent of which model the in-Desk widget uses. If you want the MCP server itself to call out to multiple LLMs, that's not what MCP servers do; they expose tools, the LLM client picks the model.

If you want a *model-agnostic agent* that an external client can talk to, expose your `chat_stream` itself as an MCP tool:

```python
@mcp.tool()
def ask_erpnext_assistant(message: str, model_label: str | None = None) -> str:
    """Run the full ERPNext agent with tools, return the final answer."""
    return _call("lazychat_erpnext.api.chat_sync", message=message, model_label=model_label)
```

Now Claude Desktop can use *any* provider you've configured inside ERPNext, by name, just by saying "ask the ERPNext assistant using the NVIDIA model".

---

## 10. Suggested rollout order

1. **Doctypes + fixtures** — add `LLM Provider`, `LLM Model`, seed presets. Verify they show up in Frappe UI.
2. **Adapters** — drop in `providers/` package. Unit-test `_to_oai_messages` and `_from_oai_message` round-trips with a sample agent transcript.
3. **Bridge swap** — replace the body of `run_agentic_turn`. Smoke test against Anthropic first (no behaviour change expected).
4. **Add a second provider** — OpenRouter is easiest because it lets you test multiple models with one key. Add a `LLM Model` record for `anthropic/claude-sonnet-4-6` via OpenRouter and confirm the OpenAI adapter produces the same answers as the Anthropic adapter for the same prompt.
5. **Model picker UI** — header dropdown + localStorage.
6. **Usage tracking** — show input/output tokens + cost estimate per turn.
7. **Toolless fallback** — only if you actually need to support models without tool use.
8. **Streaming adapters** — last, and only if §8 caveats are acceptable to you.

The whole thing is ~600 LoC of new Python plus a small JS patch — pretty cheap for "any LLM, swappable at runtime, with tool use across the lot."
