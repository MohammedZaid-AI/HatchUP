# Deploy HatchUp With Netlify

This repo is now set up for a split deployment:

- Netlify serves the public landing page, legal pages, and `/static` assets.
- Netlify proxies app routes and API routes to a separately hosted FastAPI backend.

## What Netlify Hosts

- `/`
- `/privacy`
- `/terms`
- `/static/*`

## What Still Needs a Backend

These routes are proxied to `HATCHUP_BACKEND_ORIGIN`:

- `/dashboard`
- `/vc`
- `/vc/*`
- `/founder`
- `/founder-mode`
- `/founder/*`
- `/talent-scout`
- `/chat`
- `/research`
- `/hatchup_chat`
- `/api/*`
- `/healthz`

## Required Netlify Environment Variables

- `HATCHUP_BACKEND_ORIGIN`
  Example: `https://your-backend.onrender.com`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`

## Netlify Build Settings

- Build command: `python3 scripts/build_netlify.py`
- Publish directory: `netlify_dist`

If you connect the repo through the Netlify UI, `netlify.toml` already provides these values.

## Recommended Setup

1. Deploy the current FastAPI backend to Render, Fly.io, Railway, or another Python host.
2. Copy that backend URL into Netlify as `HATCHUP_BACKEND_ORIGIN`.
3. Add `SUPABASE_URL` and `SUPABASE_ANON_KEY` in Netlify.
4. Deploy the site on Netlify.

## Local Build Check

Run:

```bash
HATCHUP_BACKEND_ORIGIN=https://your-backend.example.com python3 scripts/build_netlify.py
```

That creates `netlify_dist/` with:

- static HTML pages
- copied `/static` assets
- a generated `_redirects` file for backend proxying
