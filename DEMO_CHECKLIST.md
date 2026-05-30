# Demo Checklist

Use this checklist right before a live demo. Keep the flow browser-first and avoid changing configuration during rehearsal.

## Environment

- `.env` is present locally and not modified during the demo session.
- Python virtual environment is activated.
- Recommended runtime is Python 3.10-3.12. Python 3.14 can work but still emits a torch/sentence-transformers warning.
- MongoDB Atlas is reachable and points to the intended demo database.
- If seller/enrichment will be shown, `ENABLE_SELLER_TOOLS=true`, `ENABLE_WEB_ENRICHMENT=true`, and valid `ADMIN_TOKEN` / `SELLER_TOKEN` exist in `.env`.

## Startup

- Start backend: `python -m uvicorn src.api.app:app --reload`
- Start frontend (from repo root): `cd frontend`, `npm install`, `npm run dev`
- Check health: `/api/health` returns `200`.
- Frontend loads successfully at `http://localhost:5173`.

## Core Demo Flow

- Select a demo user and confirm homepage cards load.
- Open a product detail page and confirm images, product text, and score breakdown render.
- Open similar products and confirm semantic / CF explanations appear when expected.
- Run at least one search query and confirm results load with personalized reranking.
- Optionally open onboarding preview and confirm preview works before saving.

## Seller / Enrichment Flow

- Open seller page and paste seller or admin token into the access-token field.
- Create a draft successfully.
- Run draft validation successfully.
- Run index preview successfully.
- Run enrichment preview or request successfully.
- Apply one enrichment suggestion successfully.
- Do not run approve-index unless you intentionally want additive catalog writes for the demo.

## Debug / Admin

- Open Debug/Admin with admin token if that page is part of the demo.
- Confirm lineage, counts, and protected collection warnings render.
- Keep reset/rebuild actions on dry-run unless a human explicitly approves a write.

## Final Safety Check

- No emergency config toggles were changed mid-demo.
- No live reset/write commands are queued in another terminal.
- If anything drifts, fall back to a shopper-first browser demo; seller/admin write actions remain optional.
