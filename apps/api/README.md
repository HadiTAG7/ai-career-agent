# AI Career Agent API

FastAPI backend for the evidence-first career agent. The service never fetches job-board
pages and its default deterministic provider never sends career data to an external model.

## Local setup

From the repository root on Windows, the recommended local launcher prepares the
safe SQLite configuration and starts both the API and web app:

```powershell
.\dev.cmd
```

To run only the API manually:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
$env:ENVIRONMENT="development"
$env:DATABASE_URL="sqlite+aiosqlite:///./career_agent.db"
$env:AUTO_CREATE_SCHEMA="true"
uvicorn career_agent_api.main:app --app-dir src --reload --port 8000
```

Development auth accepts `X-User-Id`; without it the API uses the explicit `demo-user`.
Production requires Clerk JWKS configuration and accepts only `Authorization: Bearer ...`.

## Database and worker

```powershell
alembic upgrade head
python -m career_agent_api.seed
celery -A career_agent_api.worker:celery_app worker --loglevel=INFO
```

## Quality checks

```powershell
pytest
ruff check .
```

Health endpoints are `/health/live` and `/health/ready`; OpenAPI is served at `/docs`.

## Career-path assistant

The persisted career-path chat is available at `/v1/career-path`. External AI is disabled by
default. After completing the project's privacy, data-transfer, and provider review, local
development can enable Mistral in `apps/api/.env`:

```dotenv
AI_PROVIDER=mistral
MISTRAL_API_KEY=replace-with-your-mistral-key
AI_MODEL=mistral-small-2603
AI_SAFETY_SALT=replace-with-a-long-random-secret
```

For OpenAI, select `AI_PROVIDER=openai`, set `OPENAI_API_KEY`, and choose an OpenAI model instead.
Never put either secret in `apps/web` or a `NEXT_PUBLIC_*` variable.

Restart the API after changing these values. Provider keys remain server-side. Both integrations
send a bounded local conversation context, filter identity and unconfirmed profile data, require
fresh data-sharing acknowledgement when the provider changes, and never turn a chat statement into
a confirmed career fact. OpenAI uses the Responses API with `store=false`. Mistral uses stateless
Chat Completions with strict JSON Schema; account-level retention and data-sharing controls still
need review before real personal data or production use.

## Safety contracts

- `POST /v1/profiles/{profile_id}/imports` accepts bounded PDF/DOCX/LinkedIn ZIP files. It
  stores a hash and extracted candidates, never the raw upload; every candidate remains
  `extracted` until the user confirms it. Empty extractions are rejected, and the same file
  hash cannot be imported twice into one profile.
- `GET /v1/profiles/{profile_id}/summary` is the shared source for profile quality and review
  counts used by both the profile UI and dashboard.
- `POST /v1/documents` renders content only from typed claim units. Factual claims require
  confirmed, same-profile evidence of a compatible category, and numeric claims may not add
  numbers absent from that evidence.
- Job URLs are stored as user input. This service has no job-board fetch or auto-submit route;
  every source policy is deny-by-default.
- `GET /v1/me/export` exports only the authenticated owner's records, while
  `DELETE /v1/me/data` removes them (including career-path messages) and returns a non-identifying
  deletion receipt.
