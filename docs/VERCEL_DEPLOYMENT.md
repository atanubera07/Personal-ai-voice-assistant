# Vercel backend deployment

Prepared project: https://vercel.com/atanus-projects/personal-ai-agent-backend

Status: project created; no deployment or database yet. Root directory is `backend`,
framework is FastAPI, and `index.py` exposes the existing ASGI application.
The source is on `codex/production-candidate-v06` in
`atanubera07/Personal-ai-voice-assistant`. The main branch only contains a bootstrap
README. Do not deploy main until the candidate has been reviewed and merged.

## Required database setup

In the Vercel project's Storage tab, create a dedicated Neon PostgreSQL database
and connect it to this project. Use a free plan if offered; otherwise review the
price before proceeding. Do not connect the BloodSync database.
Keep connection strings in Vercel environment variables, not chat or GitHub.

Use the pooled PostgreSQL URL for runtime `DATABASE_URL`, with the SQLAlchemy
scheme `postgresql+psycopg://` and TLS enabled. Use the direct database connection
for migrations. The current application does not normalize `postgres://` or
`postgresql://` automatically.

## Operator completion steps

1. Set independent cryptographically random `OWNER_SECRET`, `JWT_SECRET`, and
   `WEBHOOK_SECRET` (at least 32 characters), and a Fernet `DATA_KEY` in the project.
   Retain encryption keys securely for recovery; never regenerate on deployment.
2. Set `SIMULATION=false`, `CALENDAR_PROVIDER=disabled`, and `PUBLIC_ORIGIN` to
   the final HTTPS application origin without a path.
3. Load the same environment privately into an operator session, run
   `alembic upgrade head` from `backend`, then verify the migration revision.
   Never run migrations from a function import or per-request handler.
4. Deploy the reviewed candidate source. The project is not yet connected to Git.
   Remove Vercel SSO protection only for the intended app endpoint once application
   authentication is configured, because the Android client cannot complete Vercel
   SSO. Keep application device authentication enabled.
5. Verify `/health`, `/ready`, unauthorized API rejection, request signatures,
   host/HTTPS checks, and that live provider endpoints remain disabled remotely.
6. Generate a five-minute token using `python -m app.admin pair` with the production
   database environment. Enter it in Android Settings with the verified HTTPS URL.
7. Schedule `python -m app.admin cleanup` hourly using a trusted operator job.
   No scheduler has been provisioned for this project.

Vercel functions have ephemeral filesystems. Do not use SQLite or local recording
storage on this deployment. The unconnected recording component, live calling,
push delivery and general AI chat remain unavailable. This setup has not yet been
validated on a live Vercel deployment.
