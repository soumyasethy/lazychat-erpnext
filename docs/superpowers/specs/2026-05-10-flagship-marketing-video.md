# Flagship Marketing Video — Top of README (Cycle 13.3)

**Goal:** Replace the 37s `demo.mp4` with an 80-second story-driven flagship video that positions lazychat.ai as a product (not a feature catalog), uses the user's verbatim consultant queries, demonstrates BYO LLM in 30 seconds, and contains zero brand-name leaks.

**Audience:** ERPNext consultants & developers who lose hours every week on stakeholder ad-hoc report requests.

**Architecture:** Synthetic-injection capture via Playwright + postMessage envelopes (proven from Cycle 13.2) — no real LLM, no real DB, no real customer data. Background page (Sales Invoice list) is filtered to 0 rows so no brand-named records leak around the panel edges. Overlays composited as HTML divs *during* capture (not ffmpeg drawtext) for accurate fade timing.

**Tech Stack:** Playwright (headless Chromium @ 1440×900), postMessage `injectMessage` envelopes, ffmpeg (webm → mp4 H.264 with `-movflags +faststart`).

---

## Story framework: Problem-Agitate-Solve (PAS)

Justified: B2B productivity tool, viscerally painful before-state (manual report grinding), clean after-state (typed sentence → report URL). PAS gives the consultant the cathartic "yes that's my Tuesday" hook then earns the reveal.

---

## Scene plan (80s total)

| t | Scene | Mechanism |
|---|---|---|
| 0–4s | HOOK: "Your stakeholder just asked for another ad-hoc report by EOD." | Page background filtered to 0 rows + large overlay text |
| 4–10s | AGITATE: "The old way takes 90 minutes." Strike-through 3-step pain | Pure HTML overlay (no recording underneath) |
| 10–18s | OPEN: Click FAB, panel slides in, type Q1 verbatim | Real `applyHeroLayout` + `typeIntoComposer` |
| 18–32s | DISPATCH: user msg + 2 mcpTool cards + 324-row result table | `injectMessage` envelopes (DemoCo suppliers) |
| 32–55s | PLAN→APPLY: type Q2, plan card, prepare_create_report Apply card with sample, Done w/ Open Report button | `injectMessage` (planMsg + previewAction) |
| 55–70s | BYO LLM: open model picker, paste sanitized NVIDIA curl, fields populate, Test connection green | Real UI clicks on ModelEditor; key redacted to `nvapi-***` |
| 70–80s | CTA: hero hold + "★ Star on GitHub" + repo URL + "94 tools · permission-aware · Apply-gated" | HTML overlay over final panel state |

---

## Brand-leak guards

| Risk | Guard |
|---|---|
| Sales Invoice list shows real customer rows | Navigate to `/app/sales-invoice/view/list?customer=__demo_no_match__` — yields 0 rows; "No Sales Invoices found" empty state renders |
| Panel content shows real records | All injected via `injectMessage` with hand-curated DemoCo data — never reads DB |
| Tool result preview leaks data | `resultPreview` field fully synthetic; SQL strings reference `\`tabPurchase Invoice\`` but never execute |
| BYO LLM curl leaks real key | Sanitize to `Bearer nvapi-EXAMPLE-KEY`; the user's real key from the brief is NOT used verbatim |
| Browser tabs / window chrome | Headless Chromium — no system chrome captured; viewport is exactly 1440×900 |

**Verification gate (mandatory before commit):**
1. `grep -irE 'lotto|agilitas|one8|lottosport' /tmp/playwright-video/` returns empty
2. `grep -irE 'lotto|agilitas|one8|lottosport' lazychat-erpnext/.github/assets/*.png` returns empty (visual frames)
3. Sample 10 frames from final mp4 via `ffmpeg -ss N -frames:v 1` and eyeball each for any leaked text in the page background

---

## Files

| Path | Kind | Purpose |
|---|---|---|
| `/tmp/record_flagship_video.mjs` | NEW | Playwright recorder; 7-scene `injectFlow()` per scene; uses HTML overlay divs for caption animations |
| `/tmp/compose_flagship_video.sh` | NEW | ffmpeg conversion: webm → mp4 H.264 CRF 22, faststart, 30fps, scale 1440 |
| `lazychat-erpnext/.github/assets/demo.mp4` | REPLACE | The 80s flagship (was 37s) |
| `lazychat-erpnext/.github/assets/hero-panel-open.png` | REPLACE | Frame 5 still composition |
| `lazychat-erpnext/.github/assets/story-{01,02,03}-*.png` | REPLACE | Recapture with filtered-list background |
| `lazychat-erpnext/.github/assets/byok-{01,02,03}-*.png` | REPLACE | Recapture with sanitized curl key |
| `lazychat-erpnext/README.md` | MODIFY | Tighten hero copy to match new 80s video story; bump `<video>` `<source>` if needed |

---

## Out of scope

- Voiceover (GitHub READMEs autoplay muted — captions carry the story)
- Background music (ditto)
- Cinematic b-roll (developer tools lose credibility with film-production polish; screen recording is the right register)
- Per-scene custom fonts / typography (system font is 100% adequate at 80s scale)
- Real LLM dispatch (deterministic synthetic injection is visually identical and zero-risk for brand leaks)

---

## Execution order

1. Write `/tmp/record_flagship_video.mjs` — 7 scene functions + main runner
2. Run capture → produces raw `.webm` in `/tmp/playwright-video/flagship/`
3. Write `/tmp/compose_flagship_video.sh` — ffmpeg conversion + final placement
4. Run compose → produces `.github/assets/demo.mp4`
5. Recapture brand-safe stills via similar mechanism (extend the recorder or add a stills runner)
6. Run brand-leak verification (grep + frame audit)
7. Update README hero copy
8. Run local link audit + 94/94 catalog re-check
9. Commit on `cycle-13-readme-rewrite`; await user push approval per project conventions
