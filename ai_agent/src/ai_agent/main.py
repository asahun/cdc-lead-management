import logging
from fastapi import FastAPI

from ai_agent.graph import build_graph
from ai_agent.schemas import RunRequest
from ai_agent.settings import get_settings
from ai_agent.tools.db import PostgresClient
from ai_agent.utils.audit import add_error, ensure_audit
from ai_agent.utils.logging import setup_logging


setup_logging()
logger = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(title="LoadRouter AI Agent", version="v1")

db_client = PostgresClient(settings)
agent_graph = build_graph(db_client, settings)


@app.get("/health")
def health_check():
    db_ok = db_client.check_connection()
    openai_ok = bool(settings.openai_api_key)
    google_ok = bool(settings.google_cse_api_key and settings.google_cse_cx)
    return {
        "ok": True,
        "dependencies": {
            "db": {"ok": db_ok},
            "openai": {"ok": openai_ok},
            "google_cse": {"ok": google_ok},
        },
    }


@app.on_event("startup")
def startup():
    db_client.ensure_tables()


@app.post("/run")
def run_agent(payload: RunRequest):
    state = {
        "input": payload,
        "audit": {"steps": [], "errors": []},
    }
    try:
        logger.info("agent run started: business_name=%s", payload.business_name)
        result = agent_graph.invoke(state)
        response = result.get("response")
        if not response:
            raise ValueError("Agent response missing")
        logger.info("agent run completed: saving result")
        db_client.save_latest_run(
            str(payload.business_id) if payload.business_id is not None else None,
            payload.business_name,
            payload.state,
            payload.model_dump(),
            response,
            status="completed",
            error_message=None,
        )
        logger.info("agent run response ready")
        return response
    except Exception as exc:
        logger.exception("agent run failed")
        audit = ensure_audit(state)
        add_error(audit, f"run error: {exc}")
        response = {
            "input": payload.model_dump(),
            "analysis": {},
            "audit": audit,
        }
        db_client.save_latest_run(
            str(payload.business_id) if payload.business_id is not None else None,
            payload.business_name,
            payload.state,
            payload.model_dump(),
            response,
            status="error",
            error_message=str(exc),
        )
        return response


def main():
    import uvicorn

    uvicorn.run(
        "ai_agent.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
