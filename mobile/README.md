# NewNews field app (Expo Go)

Ingest stories (text + photo) and run editorial review from a phone — same public
API the website uses. No separate backend, no separate app for editors: **Ingest**
and **Review** are tabs.

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

1. **Ingest tab** — write a story, snap a photo (Camera) or pick one (Gallery), Submit.
   Note the item id. If the worker beats you to it, media upload 409s — resubmit (the
   attach-while-`received` race is documented in `docs/requirements.md` FR-15).
2. **Website `/live`** (same client key) — keep it open in a browser.
3. **Review tab** — Reload queue → open the item (score, certainty, AI rationale, audit
   trail) → Approve with a note (or Reject with a reason).
4. **Website** — the approved item arrives on `/live` with its `editorially_reviewed`
   badge; `/feed` shows it on reload.

Photo OCR path: photograph any Nepali/English printed text — `extract_media` OCRs it
before the AI assessment sees it.
