# LoadRouter AI Agent (v1)

## Environment
Create `.env` at repo root (or set env vars in your shell):

```
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-5.1

DB_HOST=db
DB_PORT=5432
DB_NAME=ucp
DB_USER=ucp_app
DB_PASSWORD=your_password

GOOGLE_CSE_API_KEY=your_key_here
GOOGLE_CSE_CX=your_cse_id
GOOGLE_PLACES_API_KEY=your_key_here
GSA_SITE_SCANNING_API_KEY=DEMO_KEY
WEB_SCRAPE_ENABLED=true
AI_AGENT_URL=http://localhost:8088
```

## Run
From the repo root:

```
docker compose up --build
```

## How It Works (V1.5)
- Reuses the existing GPT prompt + response schema from `services/prompts/` (copied into `ai_agent`).
- Never reads from the `property` table (blocked in code).
- Stores only the latest run per business (older runs are deleted in `agent_runs`).
- Adds a deterministic `resolution` block (candidates, confidence, needs_review, reason_code).

## Test
Health:

```
curl http://localhost:8088/health
```

Run:

```
curl -X POST http://localhost:8088/run \
  -H 'Content-Type: application/json' \
  -d '{
    "business_name": "Acme Holdings",
    "state": "GA",
    "property_ids": ["P-123", "P-456"]
  }'
```

## Troubleshooting
- Inside Docker, the DB host is `db` (service name). From your host machine, it is `localhost`.
- If `/health` shows `db.ok=false`, confirm Postgres is up and `.env` matches your DB credentials.
- GA SOS lookup reads from your local Postgres SOS tables (biz_entity, biz_entity_registered_agents).
- The agent never reads from the `property` table; access is blocked in code.

## Data Migration (existing Docker volume)
If you have an existing Postgres volume (example: `projects_postgres_data`) and want to migrate into this
compose DB (`lead_app-db-1`), use these exact commands:

1) Start a temporary container with the old volume:

```
docker run -d --name old_db_dump -e POSTGRES_PASSWORD='EJe5&fWgxt6gow' -v projects_postgres_data:/var/lib/postgresql/data postgres:15
```

2) Dump from the old DB:

```
docker exec old_db_dump pg_dump -U ucp_app -d ucp -f /tmp/ucp_dump.sql
```

3) Copy the dump to your host:

```
docker cp old_db_dump:/tmp/ucp_dump.sql ./ucp_dump.sql
```

4) Copy into the new DB container and restore:

```
docker cp ucp_dump.sql lead_app-db-1:/tmp/ucp_dump.sql
docker exec -it lead_app-db-1 psql -U ucp_app -d ucp -f /tmp/ucp_dump.sql
```

5) Cleanup the temporary container:

```
docker stop old_db_dump
docker rm old_db_dump
```
