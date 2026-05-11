# 75-second demo recording — script + capture commands

This is the canonical script for `.github/assets/demo.mp4` (the README hero video). Re-record any time the UI changes meaningfully so the README stays current.

## Pre-flight (once before recording)

```bash
# Ensure feature flags are wired so the demo shows the modern UI
cd /path/to/your/frappe-bench
bench --site erp.local execute frappe.db.set_value \
  --kwargs '{"dt":"Lazychat Settings","dn":"Lazychat Settings","field":"cycle9_enabled","val":1}'
bench --site erp.local execute frappe.db.set_value \
  --kwargs '{"dt":"Lazychat Settings","dn":"Lazychat Settings","field":"allow_email","val":1}'
bench --site erp.local clear-cache

# Make sure dev bench is up
bench start
```

Open [`http://localhost:8000/app/sales-invoice`](http://localhost:8000/app/sales-invoice) in a fresh Chrome window. Set window size to `1920×1080`. Hide bookmarks bar. Pick a clean tab title.

## 75-second timeline

| Time | Scene | Action |
|---|---|---|
| **0–5s** | Sales Invoice list view, ~40 rows visible | Title overlay (bottom-left): *lazychat-erpnext — talk to ERPNext* |
| **5–15s** | Click chat FAB (right edge) → panel slides out. Type into composer: *"How many unpaid invoices do we have, grouped by customer? Top 10."* | The `aggregate` tool dispatch card appears with live elapsed timer; result table renders inline beneath it. |
| **15–28s** | Type: *"Send a polite reminder email to the top 3 customers with their balance."* | Three `prepare_send_email` Apply cards stack. Each shows the small "verifier checked: ok" tag (critic verdict). |
| **28–42s** | Click Apply on card 1. Watch the 3-second auto-Apply countdown finish on cards 2-3 (Edit-auto mode behavior). | Each card transitions to a green-checked Done state. |
| **42–55s** | Type: *"Create a Sales Order for ACME with 5 units of [top item by sales]."* | `prepare_create_doc` Apply card with a diff preview; click Apply; the panel auto-opens the new SO in a new tab. |
| **55–70s** | Switch the mode chip (top-right of session header) to **Plan**. Type: *"Reconcile last month's Purchase Invoices against Purchase Receipts and flag mismatches."* | Numbered plan renders with Approve / Edit / Reject buttons; click Approve; multi-step execution streams (you'll see several tool dispatch cards). |
| **70–75s** | End frame: panel docked, mascot visible. Overlay text: *★ on GitHub*. | Quiet outro. |

## Capture commands

```bash
# Recorder: macOS QuickTime → File → New Screen Recording → "Record Selected Portion"
# Audio: off (no narration; we let the visuals carry it).
# Output saved to: ~/Desktop/lazychat-demo.mov

# Convert + compress to mp4 (CRF 22 = visually lossless; CRF 26 if file > 10 MB)
ffmpeg -i ~/Desktop/lazychat-demo.mov \
  -vcodec libx264 -crf 22 -preset slow -movflags +faststart \
  -vf "scale=1920:-2:flags=lanczos" \
  -an .github/assets/demo.mp4

# Verify size
ls -lh .github/assets/demo.mp4
```

## Extract still frames for "What you get" tile strip

```bash
ffmpeg -i .github/assets/demo.mp4 -ss 12 -vframes 1 .github/assets/01-tools.png
ffmpeg -i .github/assets/demo.mp4 -ss 25 -vframes 1 .github/assets/02-critic.png
ffmpeg -i .github/assets/demo.mp4 -ss 50 -vframes 1 .github/assets/03-apply.png
ffmpeg -i .github/assets/demo.mp4 -ss 65 -vframes 1 .github/assets/04-plan.png
```

## Upload to GitHub

The README hero uses GitHub's user-attachment URL pattern (the `https://github.com/<user>/<repo>/assets/<id>/<file>` form GitHub generates when you drag-drop a file into a comment editor).

1. Open any issue or PR on the repo.
2. Drag-drop `demo.mp4` into the comment box. GitHub uploads it and replaces with a `https://github.com/.../assets/.../demo.mp4` URL.
3. Don't post the comment — just copy that URL.
4. Paste the URL on its own line in the README hero (where the placeholder currently sits).

GitHub will render the bare URL as an inline `<video>` player automatically.

## Common gotchas

- **Black-frame on first second** of QuickTime → trim with `-ss 1` in ffmpeg.
- **File > 10 MB** → bump CRF to 26 or trim a few seconds.
- **Cursor not visible** → in QuickTime: Show Mouse Clicks in Recordings (in Recording menu).
- **Animation tearing** → record at 60 fps then re-encode at 30 fps via `-r 30`.
