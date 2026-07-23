"""Streamlit + PWA 정적 파일 + Web Push API 통합 게이트웨이."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from push_notify import run_push_check
from push_store import save_alert_snapshot, upsert_subscription, remove_subscription
from secrets_util import get_vapid_config

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
PWA_DIR = ROOT / "pwa"
STREAMLIT_PORT = int(os.environ.get("STREAMLIT_PORT", "8501"))
STREAMLIT_HOST = os.environ.get("STREAMLIT_HOST", "127.0.0.1")
STREAMLIT_BASE = f"http://{STREAMLIT_HOST}:{STREAMLIT_PORT}"
GATEWAY_PORT = int(os.environ.get("GATEWAY_PORT", "8080"))

streamlit_proc: subprocess.Popen | None = None
scheduler: AsyncIOScheduler | None = None


def start_streamlit() -> subprocess.Popen:
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ROOT / "app.py"),
        f"--server.port={STREAMLIT_PORT}",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        f"--server.address={STREAMLIT_HOST}",
    ]
    env = os.environ.copy()
    env["GATEWAY_PUBLIC_ORIGIN"] = f"http://127.0.0.1:{GATEWAY_PORT}"
    return subprocess.Popen(cmd, cwd=str(ROOT), env=env)


def stop_streamlit() -> None:
    global streamlit_proc
    if streamlit_proc and streamlit_proc.poll() is None:
        streamlit_proc.terminate()
        try:
            streamlit_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            streamlit_proc.kill()
    streamlit_proc = None


async def scheduled_push_job(force_scheduled: bool = False) -> None:
    result = await asyncio.to_thread(run_push_check, force_scheduled=force_scheduled)
    logger.info("Push check result: %s", result)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global streamlit_proc, scheduler
    if os.environ.get("GATEWAY_SKIP_STREAMLIT") != "1":
        streamlit_proc = start_streamlit()
        await asyncio.sleep(2.5)

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        scheduled_push_job,
        CronTrigger(hour="2", minute="0"),
        kwargs={"force_scheduled": True},
        id="daily_push",
        replace_existing=True,
    )
    scheduler.add_job(
        scheduled_push_job,
        "interval",
        hours=3,
        kwargs={"force_scheduled": False},
        id="change_push",
        replace_existing=True,
    )
    scheduler.start()
    yield
    if scheduler:
        scheduler.shutdown(wait=False)
    stop_streamlit()


app = FastAPI(title="Phishing Moa Gateway", lifespan=lifespan)
app.mount("/icons", StaticFiles(directory=PWA_DIR / "icons"), name="icons")


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(PWA_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker() -> Response:
    content = (PWA_DIR / "sw.js").read_text(encoding="utf-8")
    return Response(content, media_type="application/javascript", headers={"Service-Worker-Allowed": "/"})


@app.get("/api/push/vapid-public-key")
def vapid_public_key():
    public_key = get_vapid_config().get("public_key", "")
    if not public_key:
        raise HTTPException(status_code=503, detail="VAPID_PUBLIC_KEY 가 secrets.toml 에 없습니다.")
    return {"publicKey": public_key}


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    body = await request.json()
    if not body.get("endpoint"):
        raise HTTPException(status_code=400, detail="subscription.endpoint 가 필요합니다.")
    upsert_subscription(body)
    return {"ok": True}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    body = await request.json()
    endpoint = body.get("endpoint")
    if not endpoint:
        raise HTTPException(status_code=400, detail="endpoint 가 필요합니다.")
    remove_subscription(endpoint)
    return {"ok": True}


@app.post("/api/alert/snapshot")
async def alert_snapshot(request: Request):
    body = await request.json()
    if not body.get("keyword"):
        raise HTTPException(status_code=400, detail="keyword 가 필요합니다.")
    saved = save_alert_snapshot(body)
    return {"ok": True, "snapshot": saved}


@app.post("/api/push/test")
async def push_test():
    result = await asyncio.to_thread(run_push_check, force_scheduled=True)
    return result


@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
)
async def proxy_streamlit(request: Request, full_path: str):
    if full_path.startswith("api/") or full_path in {"manifest.webmanifest", "sw.js"}:
        raise HTTPException(status_code=404)

    if request.headers.get("upgrade", "").lower() == "websocket":
        raise HTTPException(status_code=400, detail="WebSocket proxy is not enabled in this build.")

    target_url = f"{STREAMLIT_BASE}/{full_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in {"host", "content-length"}
    }

    body = await request.body()
    async with httpx.AsyncClient(timeout=120.0) as client:
        upstream = await client.request(
            request.method,
            target_url,
            headers=headers,
            content=body,
        )

    response_headers = {
        key: value
        for key, value in upstream.headers.items()
        if key.lower() not in {"content-encoding", "content-length", "transfer-encoding", "connection"}
    }
    return Response(content=upstream.content, status_code=upstream.status_code, headers=response_headers)


if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    uvicorn.run("gateway:app", host="0.0.0.0", port=GATEWAY_PORT, reload=False)
