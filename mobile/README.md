# NewNews field app (Expo Go, SDK 57)

Ingest stories (text + photo) and run editorial review from a phone — same public
API the website uses. Editors work in the **Review** tab, couriers in **Ingest**,
and **Track** shows any item's pipeline journey — no separate apps. Requires Expo Go with SDK 57 support (the project pins
`expo@~57`; if your Go app is older, update it from the Play Store).

## Run it

```bash
cd mobile
npm install
npx expo start          # scan the QR with Expo Go (same Wi-Fi for LAN use)
```

## Settings tab (saved on-device)

| Field | Value |
|---|---|
| API base URL | Cloud: `https://newnews-t54x.onrender.com` · Local: your machine's **LAN IP**, e.g. `http://192.168.1.5:8000` (`localhost` means the phone itself) |
| Client key | `nn_…` from `python -m app.seed` or `POST /api/v1/clients` (ingest) |
| Admin key | `ADMIN_API_KEY` (review tab) |

## Manual end-to-end (the demo)

1. **Ingest tab** — tap 🎲 for a catalog story (stub-predicted certainty shown) or write
   your own, snap a photo (Camera) or pick one (Gallery), Submit. Copy the ID if you
   like — **Track is already prefilled** and auto-tracks it. If the worker beats the
   upload, media 409s — resubmit (the attach-while-`received` race, FR-15).
2. **Track tab** — always live: status, certainty + editorial badges, AI confidence,
   ingest→eligible→delivered latencies, editor approval note, pipeline stepper, media
   list, full audit journey. An admin board stream (`/api/v1/track/events`, audit
   watermark) refetches it on every pipeline movement — stages, approvals, new ingests
   — reconnecting by itself if the socket drops.
3. **Review tab** — Reload queue → open the item (score, certainty, rationale, attached
   media with extraction status, audit) → Approve with a note (or Reject with a reason).
4. **Deliver tab** — live by default (SSE push, items appended straight from the frame;
   auto-reconnects) with Pause/Resume plus Reload (REST pull) as a fallback.
5. **Website** — same over `/live`, `/feed`, `/track` in a browser.

Photo OCR path: photograph any Nepali/English printed text — `extract_media` OCRs it
before the AI assessment sees it.
