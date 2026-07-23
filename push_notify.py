"""피싱 주의보 Web Push 발송·변화 감지."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

import requests
from pywebpush import WebPushException, webpush

from push_store import (
    get_alert_snapshot,
    get_last_push_state,
    list_subscriptions,
    remove_subscription,
    save_last_push_state,
    save_subscriptions,
)
from secrets_util import get_naver_credentials, get_vapid_config

logger = logging.getLogger(__name__)

ALERT_LOOKBACK_DAYS = 14
SEED_QUERIES = ("피싱", "보이스피싱", "금융사기")
KEYWORD_HINTS = (
    "딥페이크",
    "스미싱",
    "큐싱",
    "메신저피싱",
    "몸캠피싱",
    "기관사칭",
    "지인사칭",
    "투자사기",
    "전세사기",
    "로맨스스캠",
    "렌탈 사기",
    "렌터카 사기",
    "정부지원금 사기",
    "신종 사기",
    "보이스피싱",
    "피싱",
    "금융사기",
)


def _clean_html(text: str) -> str:
    import re

    text = re.sub(r"<.*?>", "", text or "")
    return (
        text.replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .strip()
    )


def _match_keywords(text: str) -> list[str]:
    found: list[str] = []
    lowered = text.lower()
    for keyword in KEYWORD_HINTS:
        if keyword.lower() in lowered and keyword not in found:
            found.append(keyword)
    return found


def fetch_alert_snapshot_from_api() -> dict | None:
    """네이버 API로 간단히 최상위 주의 키워드를 계산합니다."""
    client_id, client_secret = get_naver_credentials()
    if not client_id or not client_secret:
        return None

    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }
    past_alert = datetime.now() - timedelta(days=ALERT_LOOKBACK_DAYS)
    counts: dict[str, int] = {}

    for query in SEED_QUERIES:
        try:
            res = requests.get(
                url,
                headers=headers,
                params={"query": query, "display": 100, "start": 1, "sort": "date"},
                timeout=10,
            )
            res.raise_for_status()
            items = res.json().get("items", [])
        except requests.RequestException as exc:
            logger.warning("Alert fetch failed for %s: %s", query, exc)
            continue

        for item in items:
            try:
                from email.utils import parsedate_to_datetime

                pub_date = parsedate_to_datetime(item["pubDate"]).replace(tzinfo=None)
            except Exception:
                continue
            if pub_date < past_alert:
                continue
            title = _clean_html(item.get("title", ""))
            description = _clean_html(item.get("description", ""))
            for keyword in _match_keywords(f"{title} {description}"):
                if keyword in {"피싱", "금융사기", "보이스피싱"}:
                    continue
                counts[keyword] = counts.get(keyword, 0) + 1

    if not counts:
        return None

    keyword, count = max(counts.items(), key=lambda item: item[1])
    return {
        "keyword": keyword,
        "count": count,
        "how": f"최근 2주 보도에서 「{keyword}」 관련 피싱·사기 수법이 {count}회 언급되었습니다.",
        "watch": "금전·개인정보 요구, 링크·앱 설치 유도가 있으면 일단 중단하고 공식 경로로 확인하세요.",
        "source": "api",
    }


def resolve_alert_snapshot() -> dict | None:
    stored = get_alert_snapshot()
    if stored and stored.get("keyword"):
        return stored
    return fetch_alert_snapshot_from_api()


def build_push_payload(snapshot: dict, reason: str) -> dict:
    keyword = snapshot.get("keyword", "피싱")
    count = snapshot.get("count", 0)
    watch = snapshot.get("watch") or "의심 연락은 바로 끊고 112·1332로 확인하세요."
    title = "🚨 피싱 주의보"
    if reason == "scheduled":
        body = f"「{keyword}」 최근 2주 {count}회 언급 · {watch[:80]}"
    else:
        body = f"주의 키워드가 「{keyword}」(최근 2주 {count}회)로 갱신되었습니다."
    return {
        "title": title,
        "body": body,
        "url": "/",
        "tag": f"alert-{keyword}-{count}",
    }


def send_web_push(subscription: dict, payload: dict) -> bool:
    vapid = get_vapid_config()
    if not vapid["public_key"] or not vapid["private_key"]:
        logger.error("VAPID keys are missing in secrets.toml")
        return False

    try:
        webpush(
            subscription_info=subscription,
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid["private_key"],
            vapid_claims={"sub": vapid["claims_email"]},
        )
        return True
    except WebPushException as exc:
        logger.warning("Push failed: %s", exc)
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            endpoint = subscription.get("endpoint")
            if endpoint:
                remove_subscription(endpoint)
        return False


def broadcast_push(payload: dict) -> tuple[int, int]:
    subscriptions = list_subscriptions()
    if not subscriptions:
        return 0, 0

    ok = 0
    failed = 0
    for sub in subscriptions:
        if send_web_push(sub, payload):
            ok += 1
        else:
            failed += 1
    save_subscriptions(list_subscriptions())
    return ok, failed


def should_send_change_push(snapshot: dict) -> bool:
    last = get_last_push_state()
    prev_keyword = last.get("keyword")
    prev_count = last.get("count")
    keyword = snapshot.get("keyword")
    count = snapshot.get("count")
    if prev_keyword != keyword:
        return True
    if isinstance(prev_count, int) and isinstance(count, int) and abs(count - prev_count) >= 2:
        return True
    return False


def mark_push_sent(snapshot: dict, reason: str) -> None:
    save_last_push_state(
        {
            "keyword": snapshot.get("keyword"),
            "count": snapshot.get("count"),
            "reason": reason,
        }
    )


def run_push_check(*, force_scheduled: bool = False) -> dict:
    snapshot = resolve_alert_snapshot()
    if not snapshot:
        return {"sent": False, "reason": "no_snapshot"}

    if force_scheduled:
        payload = build_push_payload(snapshot, "scheduled")
        ok, failed = broadcast_push(payload)
        mark_push_sent(snapshot, "scheduled")
        return {
            "sent": ok > 0,
            "reason": "scheduled",
            "ok": ok,
            "failed": failed,
            "snapshot": snapshot,
        }

    if should_send_change_push(snapshot):
        payload = build_push_payload(snapshot, "changed")
        ok, failed = broadcast_push(payload)
        mark_push_sent(snapshot, "changed")
        return {
            "sent": ok > 0,
            "reason": "changed",
            "ok": ok,
            "failed": failed,
            "snapshot": snapshot,
        }

    return {"sent": False, "reason": "unchanged", "snapshot": snapshot}


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--scheduled", action="store_true")
    args = parser.parse_args()
    result = run_push_check(force_scheduled=args.scheduled)
    print(json.dumps(result, ensure_ascii=False, indent=2))
