# Deploy HatchUp On Render

## Recommended Setup

Use a Render `Web Service` for this FastAPI app and keep `Supabase` for auth, database, and storage.

This repo now includes [render.yaml](/d:/Zaids%20Work/HatchUP/render.yaml), so you can deploy with Render Blueprints or copy the same settings manually in the Render dashboard.

## Start Command

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Required Environment Variables

Set these in Render:

```text
SUPABASE_URL
SUPABASE_ANON_KEY
SUPABASE_SERVICE_ROLE_KEY
GROQ_API_KEY
```

Optional, depending on your setup:

```text
SUPABASE_DB_URL
DATABASE_URL
TAVILY_API_KEY
GOOGLE_API_KEY
REDDIT_CLIENT_ID
REDDIT_CLIENT_SECRET
```

## Deploy Steps

1. Push this repo to GitHub.
2. In Render, choose `New +` -> `Blueprint`.
3. Select this repository.
4. Review the generated web service from `render.yaml`.
5. Fill in the missing secret environment variables.
6. Deploy.

## Health Check

Render can use:

```text
/healthz
```

## Important Note About OCR

This project includes `pytesseract` in [requirements.txt](/d:/Zaids%20Work/HatchUP/requirements.txt) and imports it in [document_parser.py](/d:/Zaids%20Work/HatchUP/src/document_parser.py).

That means OCR-heavy flows may need the native `tesseract` binary installed on the host. If deck parsing works for PDFs/PPTX but OCR-based image extraction fails on Render, the safest next step is to switch this app to a Docker-based Render deploy so system packages can be installed explicitly.

## Free Plan Expectations

Render free is fine for testing and demos, but expect:

- service sleep after inactivity
- cold starts
- limited monthly instance hours
- weaker performance for heavier analysis jobs
