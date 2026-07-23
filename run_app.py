"""피싱 Moa Moa — Streamlit + PWA + Web Push 통합 실행."""

from __future__ import annotations

import logging
import os

import uvicorn

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    port = int(os.environ.get("GATEWAY_PORT", "8080"))
    print(f"\n▶ 브라우저에서 http://127.0.0.1:{port} 로 접속하세요.")
    print("  (PWA·푸시 알림은 이 주소로 접속해야 동작합니다.)\n")
    uvicorn.run("gateway:app", host="0.0.0.0", port=port, reload=False)
