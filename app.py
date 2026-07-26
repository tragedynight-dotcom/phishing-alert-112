import html
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# 1. 페이지 설정
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="🚨 피싱 범죄 Da Moa",
    page_icon="🚨",
    layout="centered",
)


def inject_pwa_head() -> None:
    """홈 화면 추가 시 'Streamlit' 대신 앱 이름·👮 아이콘이 보이도록 부모 문서 head 수정."""
    components.html(
        """
        <script>
        (function () {
          const doc = window.parent.document;
          const APP_NAME = "피싱 범죄 Da Moa";
          const SHORT_NAME = "Da Moa";
          const ICON = "/app/static/icon.svg";
          const MANIFEST = "/app/static/manifest.json";

          doc.title = APP_NAME;

          function upsertMeta(name, content, attr) {
            attr = attr || "name";
            let el = doc.querySelector("meta[" + attr + '="' + name + '"]');
            if (!el) {
              el = doc.createElement("meta");
              el.setAttribute(attr, name);
              doc.head.appendChild(el);
            }
            el.setAttribute("content", content);
          }

          upsertMeta("application-name", SHORT_NAME);
          upsertMeta("apple-mobile-web-app-title", SHORT_NAME);
          upsertMeta("apple-mobile-web-app-capable", "yes");
          upsertMeta("mobile-web-app-capable", "yes");
          upsertMeta("theme-color", "#b91c1c");

          if (!doc.querySelector('link[rel="manifest"]')) {
            const manifestLink = doc.createElement("link");
            manifestLink.rel = "manifest";
            manifestLink.href = MANIFEST;
            doc.head.appendChild(manifestLink);
          }

          if (!doc.querySelector('link[rel="apple-touch-icon"]')) {
            const touch = doc.createElement("link");
            touch.rel = "apple-touch-icon";
            touch.href = ICON;
            doc.head.appendChild(touch);
          }

          if (!doc.querySelector('link[rel="icon"]')) {
            const fav = doc.createElement("link");
            fav.rel = "icon";
            fav.href = ICON;
            doc.head.appendChild(fav);
          }
        })();
        </script>
        """,
        height=0,
    )


inject_pwa_head()

if "display_count" not in st.session_state:
    st.session_state.display_count = 3
if "display_count_all" not in st.session_state:
    st.session_state.display_count_all = 5
if "moa_display_count" not in st.session_state:
    st.session_state.moa_display_count = 5
if "moa_last_picked" not in st.session_state:
    st.session_state.moa_last_picked = None

# 피싱 주의보 키워드 집계 기간 (일)
ALERT_LOOKBACK_DAYS = 14
# 네이버 검색 API 결과 캐시 (초) — 30분
NAVER_API_CACHE_TTL = 1800
# NAVER API Hub (콘솔: console.ncloud.com/naver-api-hub) — 구 openapi.naver.com 과 URL·헤더가 다름
NAVER_NEWS_SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"


def naver_news_search_headers(client_id: str, client_secret: str) -> dict[str, str]:
    return {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
    }


def naver_news_search_params(query: str, display: int, start: int = 1) -> dict:
    return {
        "query": query,
        "display": display,
        "start": start,
        "sort": "date",
        "format": "json",
    }

st.markdown(
    """
    <style>
    /* 입력칸 "Press Enter to submit form" 영문 안내 숨김 */
    [data-testid="InputInstructions"] {
      display: none !important;
    }
    h1.phishing-mobile-title {
      font-size: 2.25rem;
      font-weight: 600;
      margin: 0 0 0.5rem 0;
      padding: 0;
    }
    h2.phishing-mobile-title {
      font-size: 1.5rem;
      font-weight: 600;
      margin: 1rem 0 0.5rem 0;
      padding: 0;
    }
    @media (max-width: 480px) {
      .block-container {
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
        max-width: 100% !important;
        overflow-x: hidden !important;
      }
      h1.phishing-mobile-title,
      h2.phishing-mobile-title {
        white-space: nowrap !important;
        line-height: 1.12 !important;
        letter-spacing: -0.04em !important;
        word-break: keep-all !important;
        overflow: visible !important;
        width: 100%;
        max-width: 100%;
      }
      h1.phishing-mobile-title { margin-bottom: 0.35rem !important; }
      h2.phishing-mobile-title {
        margin-top: 0.6rem !important;
        margin-bottom: 0.2rem !important;
      }
    }
    .phishing-alert-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: rgba(0, 0, 0, 0.28);
      padding: 0.22rem 0.62rem;
      border-radius: 999px;
      font-size: 0.74rem;
      font-weight: 800;
      letter-spacing: 0.07em;
      margin-bottom: 0.48rem;
    }
    .phishing-alert-pulse {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #fde047;
      box-shadow: 0 0 8px #fde047;
      animation: alert-blink 1.1s ease-in-out infinite;
    }
    @keyframes alert-blink {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.35; transform: scale(0.82); }
    }
    @keyframes alert-glow {
      0%, 100% { box-shadow: 0 6px 18px rgba(127, 29, 29, 0.28); }
      50% { box-shadow: 0 6px 22px rgba(220, 38, 38, 0.42), 0 0 0 3px rgba(254, 202, 202, 0.2); }
    }
    .phishing-alert-hero {
      position: relative;
      overflow: hidden;
      background: linear-gradient(135deg, #7f1d1d 0%, #b91c1c 52%, #dc2626 100%);
      border-radius: 12px;
      padding: 0.75rem 1rem 0.85rem;
      color: #fff;
      border: 1px solid rgba(255, 255, 255, 0.2);
      box-shadow: 0 6px 18px rgba(127, 29, 29, 0.28);
      margin-bottom: 0;
      animation: alert-glow 2.4s ease-in-out infinite;
    }
    .phishing-alert-hero::after {
      content: "";
      position: absolute;
      top: -40%;
      right: -20%;
      width: 55%;
      height: 140%;
      background: radial-gradient(circle, rgba(255,255,255,0.18) 0%, transparent 68%);
      pointer-events: none;
    }
    .phishing-alert-hero .phishing-alert-label {
      font-size: 0.92rem;
      font-weight: 600;
      opacity: 0.92;
      margin-bottom: 0.12rem;
      color: #fff;
      text-align: center;
    }
    .phishing-alert-hero .phishing-alert-count {
      color: #fff;
      margin-top: 0.35rem;
      margin-bottom: 0;
    }
    .phishing-alert-keyword {
      display: block;
      font-size: clamp(1.85rem, 7vw, 2.45rem);
      font-weight: 900;
      line-height: 1.18;
      letter-spacing: -0.025em;
      text-shadow: 0 2px 8px rgba(0, 0, 0, 0.24);
      margin: 0 auto;
      color: #fff;
      word-break: keep-all;
      text-align: center;
    }
    .phishing-alert-keyword-link {
      color: #fff !important;
      text-decoration: underline !important;
      text-underline-offset: 0.14em;
      text-decoration-thickness: 2px;
      cursor: pointer;
      -webkit-tap-highlight-color: rgba(255, 255, 255, 0.25);
      touch-action: manipulation;
    }
    .phishing-alert-keyword-link:hover {
      color: #fee2e2 !important;
    }
    .phishing-alert-kw-main {
      text-align: center;
      margin: 0.08rem 0 0.35rem;
    }
    div[data-testid="stMarkdown"]:has(.phishing-alert-hero) {
      margin-bottom: 0 !important;
    }
    .phishing-alert-count {
      display: inline-block;
      margin-top: 0.1rem;
      background: rgba(255, 255, 255, 0.15);
      border: 1px solid rgba(255, 255, 255, 0.25);
      border-radius: 999px;
      padding: 0.22rem 0.7rem;
      font-size: 0.82rem;
      font-weight: 700;
      margin-bottom: 0;
    }
    .phishing-alert-count-wrap {
      text-align: center;
      margin-top: 0.35rem;
    }
    .phishing-alert-desc {
      margin: 0.2rem 0 0.65rem;
      font-size: 0.98rem;
      line-height: 1.55;
      color: #1f2937;
    }
    .phishing-alert-how {
      background: #fff7ed;
      border-left: 4px solid #ea580c;
      border-radius: 0 10px 10px 0;
      padding: 0.75rem 0.9rem;
      margin-top: 0.75rem;
      margin-bottom: 0.65rem;
      font-size: 0.95rem;
      line-height: 1.55;
      color: #431407;
    }
    .phishing-alert-watch {
      background: linear-gradient(90deg, #eff6ff 0%, #dbeafe 100%);
      border: 1px solid #93c5fd;
      border-radius: 10px;
      padding: 0.75rem 0.9rem;
      font-size: 0.94rem;
      line-height: 1.55;
      color: #1e3a8a;
    }
    .phishing-alert-watch strong {
      color: #1d4ed8;
    }
    .phishing-alert-guide-links {
      display: flex;
      flex-wrap: wrap;
      gap: 0.55rem 1rem;
      margin-top: 0.65rem;
      margin-bottom: 0.35rem;
      padding: 0.65rem 0.9rem;
      background: #f8fafc;
      border: 1px solid #cbd5e1;
      border-radius: 10px;
      font-size: 0.92rem;
      font-weight: 700;
    }
    .phishing-alert-guide-links a {
      color: #1d4ed8 !important;
      text-decoration: underline !important;
      text-underline-offset: 0.12em;
    }
    .phishing-alert-guide-links a:hover {
      color: #1e3a8a !important;
    }
    .phishing-alert-guide-sep {
      color: #94a3b8;
      font-weight: 500;
    }
    .phishing-app-analysis-block {
      border-top: 1px dashed #d1d5db;
      margin-top: 0.55rem;
      padding-top: 0.55rem;
    }
    .phishing-backseo-hero {
      position: relative;
      overflow: hidden;
      background: linear-gradient(135deg, #1e3a8a 0%, #1d4ed8 52%, #2563eb 100%);
      border-radius: 16px;
      padding: 1.15rem 1.25rem 1.2rem;
      color: #fff;
      margin: 0.25rem 0 1rem;
      border: 2px solid rgba(255, 255, 255, 0.2);
      box-shadow: 0 8px 26px rgba(30, 58, 138, 0.32);
      animation: backseo-glow 2.4s ease-in-out infinite;
    }
    @keyframes backseo-glow {
      0%, 100% { box-shadow: 0 8px 26px rgba(30, 58, 138, 0.32); }
      50% { box-shadow: 0 8px 32px rgba(37, 99, 235, 0.5), 0 0 0 3px rgba(191, 219, 254, 0.22); }
    }
    .phishing-backseo-hero::after {
      content: "";
      position: absolute;
      top: -40%;
      right: -20%;
      width: 55%;
      height: 140%;
      background: radial-gradient(circle, rgba(255,255,255,0.18) 0%, transparent 68%);
      pointer-events: none;
    }
    .phishing-backseo-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      background: rgba(0, 0, 0, 0.22);
      padding: 0.22rem 0.62rem;
      border-radius: 999px;
      font-size: 0.74rem;
      font-weight: 800;
      letter-spacing: 0.05em;
      margin-bottom: 0.48rem;
    }
    .phishing-backseo-pulse {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #93c5fd;
      box-shadow: 0 0 8px #93c5fd;
      animation: alert-blink 1.1s ease-in-out infinite;
    }
    .phishing-backseo-title {
      font-size: clamp(1.15rem, 4.5vw, 1.45rem);
      font-weight: 900;
      line-height: 1.25;
      letter-spacing: -0.02em;
      margin: 0;
    }
    .phishing-backseo-sub {
      font-size: 0.88rem;
      line-height: 1.5;
      opacity: 0.93;
      margin-top: 0.45rem;
    }
    .phishing-backseo-count {
      display: inline-block;
      margin-top: 0.55rem;
      background: rgba(255, 255, 255, 0.15);
      border: 1px solid rgba(255, 255, 255, 0.25);
      border-radius: 999px;
      padding: 0.22rem 0.7rem;
      font-size: 0.82rem;
      font-weight: 700;
      color: #fff !important;
      text-decoration: none !important;
      cursor: pointer;
      transition: background 0.15s ease;
    }
    a.phishing-backseo-count:hover {
      background: rgba(255, 255, 255, 0.28);
      color: #fff !important;
      text-decoration: none !important;
    }
    .phishing-backseo-card-label {
      font-size: 0.95rem;
      font-weight: 700;
      color: #1e3a8a;
      margin: 0.15rem 0 0.65rem;
      padding-left: 0.15rem;
      border-left: 4px solid #2563eb;
    }
    .phishing-moa-hero {
      position: relative;
      overflow: hidden;
      background: linear-gradient(135deg, #065f46 0%, #059669 50%, #10b981 100%);
      border-radius: 16px;
      padding: 1.15rem 1.25rem 1.2rem;
      color: #fff;
      margin: 0.25rem 0 1rem;
      border: 2px solid rgba(255, 255, 255, 0.22);
      box-shadow: 0 8px 26px rgba(6, 95, 70, 0.28);
      animation: moa-glow 2.4s ease-in-out infinite;
    }
    @keyframes moa-glow {
      0%, 100% { box-shadow: 0 8px 26px rgba(6, 95, 70, 0.28); }
      50% { box-shadow: 0 8px 32px rgba(16, 185, 129, 0.45), 0 0 0 3px rgba(167, 243, 208, 0.22); }
    }
    .phishing-moa-hero::after {
      content: "";
      position: absolute;
      top: -40%;
      right: -20%;
      width: 55%;
      height: 140%;
      background: radial-gradient(circle, rgba(255,255,255,0.16) 0%, transparent 68%);
      pointer-events: none;
    }
    .phishing-moa-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      background: rgba(0, 0, 0, 0.2);
      padding: 0.22rem 0.65rem;
      border-radius: 999px;
      font-size: 0.74rem;
      font-weight: 800;
      letter-spacing: 0.04em;
      margin-bottom: 0.55rem;
    }
    .phishing-moa-pulse {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #6ee7b7;
      box-shadow: 0 0 8px #6ee7b7;
      animation: alert-blink 1.1s ease-in-out infinite;
    }
    .phishing-moa-title {
      font-size: clamp(1.05rem, 4.2vw, 1.4rem);
      font-weight: 900;
      line-height: 1.25;
      letter-spacing: -0.02em;
      margin: 0;
    }
    .phishing-moa-sub {
      font-size: 0.88rem;
      line-height: 1.5;
      opacity: 0.94;
      margin-top: 0.45rem;
    }
    .phishing-moa-count {
      display: inline-block;
      margin-top: 0.55rem;
      background: rgba(255, 255, 255, 0.16);
      border: 1px solid rgba(255, 255, 255, 0.28);
      border-radius: 999px;
      padding: 0.22rem 0.7rem;
      font-size: 0.82rem;
      font-weight: 700;
      color: #fff !important;
      text-decoration: none !important;
      cursor: pointer;
      transition: background 0.15s ease;
    }
    a.phishing-moa-count:hover {
      background: rgba(255, 255, 255, 0.28);
      color: #fff !important;
      text-decoration: none !important;
    }
    .phishing-moa-card-label {
      font-size: 0.95rem;
      font-weight: 700;
      color: #065f46;
      margin: 0.15rem 0 0.15rem;
      padding-left: 0.15rem;
      border-left: 4px solid #10b981;
    }
    .phishing-moa-label-row {
      margin: 0;
    }
    .phishing-moa-picker-hint {
      font-size: 0.88rem;
      color: #047857;
      font-weight: 600;
      margin: 0.1rem 0 0.55rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
components.html(
    """
    <script>
    (function () {
      const MOBILE_MAX = 480;
      let timer = null;
      const w = window.parent && window.parent.document ? window.parent : window;
      const doc = w.document;

      function containerWidth(el) {
        const box = el.closest(".block-container") || el.parentElement || doc.body;
        return Math.max(240, box.clientWidth - 2);
      }

      function fitOne(el, maxPx) {
        const limit = containerWidth(el);
        let lo = 12;
        let hi = maxPx;
        let best = lo;
        el.style.whiteSpace = "nowrap";
        el.style.display = "block";
        while (lo <= hi) {
          const mid = Math.floor((lo + hi) / 2);
          el.style.fontSize = mid + "px";
          if (el.scrollWidth <= limit) {
            best = mid;
            lo = mid + 1;
          } else {
            hi = mid - 1;
          }
        }
        el.style.fontSize = best + "px";
      }

      function fitMobileTitles() {
        doc.querySelectorAll("h1.phishing-mobile-title, h2.phishing-mobile-title").forEach(function (el) {
          el.style.fontSize = "";
        });
        if (w.innerWidth > MOBILE_MAX) return;
        doc.querySelectorAll("h1.phishing-mobile-title").forEach(function (el) {
          fitOne(el, 32);
        });
        doc.querySelectorAll("h2.phishing-mobile-title").forEach(function (el) {
          fitOne(el, 26);
        });
      }

      function scheduleFit() {
        clearTimeout(timer);
        timer = w.setTimeout(function () {
          w.requestAnimationFrame(fitMobileTitles);
        }, 80);
      }

      w.addEventListener("resize", scheduleFit);
      w.addEventListener("load", scheduleFit);
      scheduleFit();
      new w.MutationObserver(scheduleFit).observe(doc.body, { childList: true, subtree: true });
    })();
    </script>
    """,
    height=0,
)

# 추적할 피싱 수법 키워드 (긴 키워드 우선 매칭)
PHISHING_KEYWORDS = [
    "정부지원금 사기",
    "휴대폰 렌탈 사기",
    "카셰어링 사기",
    "신종 사기",
    "로맨스스캠",
    "메신저피싱",
    "몸캠피싱",
    "보이스피싱",
    "금융기관 사칭",
    "기관사칭",
    "지인사칭",
    "딥페이크",
    "스미싱",
    "큐싱",
]

# 홍보·포상·협약·위촉·예방교육 등 범죄 본문과 무관한 기사 제외
EXCLUDE_KEYWORDS = [
    "표창장",
    "감사장",
    "포상",
    "위촉장",
    "감사패",
    "표창",
    "격려",
    "후원",
    # 명예경찰·위촉·홍보성
    "명예경찰",
    "명예 경찰",
    "명예홍보",
    "홍보대사",
    "위촉식",
    "위촉",
    "임명장",
    # 금융기관·유관기관 협약·MOU
    "업무협약",
    "업무 협약",
    "협약 체결",
    "협약식",
    "협약체결",
    "양해각서",
    "MOU",
    "mou",
    "맞손",
    "손잡",
    "협력체계",
    "협력 체계",
    "공동대응 협약",
    "금융기관과 협약",
    "은행과 협약",
    "경찰과 협약",
    "업무협력을 위한 협약",
    # 예방 교육·캠페인·홍보 행사
    "예방교육",
    "예방 교육",
    "예방캠페인",
    "예방 캠페인",
    "홍보캠페인",
    "홍보 캠페인",
    "캠페인 실시",
    "캠페인 펼",
    "인식개선",
    "인식 개선",
    "교육 실시",
    "교육실시",
    "찾아가는 교육",
    "현장교육",
    "현장 교육",
    "설명회",
    "간담회",
    "토론회",
    "세미나",
    "워크숍",
    "워크샵",
    "체험부스",
    "홍보부스",
    "홍보물",
    "홍보영상",
    "홍보 영상",
    "전단지",
    "현수막",
    "가두캠페인",
    "거리 홍보",
    "거리홍보",
    "합동 홍보",
    "합동홍보",
    "집중 홍보",
    "집중홍보",
    "대국민 홍보",
    "예방 홍보",
    "예방홍보",
    "홍보 강화",
    "홍보강화",
    "예방하자",
    "예방 나서",
    "예방활동",
    "예방 활동",
    "근절 캠페인",
    "근절캠페인",
    "주민 대상 교육",
    "어르신 대상 교육",
    "청소년 대상 교육",
    "금융교육",
    "금융 교육",
    "안전교육",
    "안전 교육",
    "범죄예방교실",
    "예방교실",
    "체험 교육",
    "체험교육",
    # 대회·공모·시상
    "공모전",
    "UCC",
    "경진대회",
    "콘테스트",
    "시상식",
    "시상",
    "수상",
    # 시책·추진·행정 홍보
    "시책 추진",
    "시책을 추진",
    "시책추진",
    "대응 방안",
    "대응방안",
    "대책 마련",
    "대책을 마련",
    "방안 마련",
    "방안을 마련",
    "인식 제고",
    "인식제고",
    # 홍보 활동·행사
    "홍보 활동",
    "홍보활동",
    "홍보 행사",
    "홍보행사",
    "홍보전",
    "개막식",
    "폐막식",
    "포럼",
    "심포지엄",
    "주의 당부",
    "유의 당부",
    # 예능·방송·웹 콘텐츠 (범죄 사례 보도 아님)
    "웹예능",
    "web예능",
    "웹 예능",
    "예능 프로그램",
    "연예 프로그램",
    "OTT 오리지널",
    "오리지널 시리즈",
    "첫 방송",
    "방송 예정",
    "공개 예정",
    "유튜브 채널",
    "유튜버",
    "크리에이터",
    "출연진",
    "조회수",
    "구독자",
    # 지역 경찰서 홍보·교육
    "경찰서장",
    "서장은",
    "서장이",
    "지구대",
    "파출소",
    "찾아가는",
    "현장 교육",
    "현장교육",
]

# 키워드 단독으로는 애매하지만, 함께 나오면 홍보·교육성으로 보는 조합
EXCLUDE_COMBO_RULES = [
    (("협약",), ("금융", "은행", "경찰", "신용", "카드", "보험", "저축")),
    (("협약",), ("예방", "근절", "대응", "협력")),
    (("체결",), ("협약", "MOU", "양해각서")),
    (("교육",), ("예방", "피싱", "보이스", "스미싱", "사기", "어르신", "주민", "학생")),
    (("홍보",), ("예방", "피싱", "보이스", "스미싱", "사기", "캠페인", "부스")),
    (("캠페인",), ("예방", "피싱", "보이스", "근절", "홍보", "사기")),
    (("안내",), ("예방", "주의사항", "당부", "홍보")),
    (("대회",), ("개최", "시상", "수상", "공모", "UCC", "경진", "콘테스트", "포스터")),
    (("시책",), ("추진", "발표", "공모", "시행", "마련", "강화")),
    (("홍보",), ("활동", "행사", "전", "나서", "강화", "실시", "펼")),
    (("추진",), ("시책", "대책", "방안", "사업", "정책", "교육")),
    (("개최",), ("대회", "행사", "교육", "설명회", "세미나", "포럼")),
    (("당부",), ("주의", "각별", "유의", "예방", "피싱", "보이스")),
    (("피싱",), ("예능", "웹예능", "웹 예능", "출연", "방송", "에피소드", "시즌")),
    (("사기",), ("예능", "웹예능", "출연", "방송", "콘텐츠", "유튜브")),
    (("예능",), ("제작", "공개", "방송", "출연", "선보", "런칭", "오픈", "시즌")),
]


PRESS_MAP = {
    "chosun.com": "조선일보",
    "joongang.co.kr": "중앙일보",
    "joins.com": "중앙일보",
    "donga.com": "동아일보",
    "yna.co.kr": "연합뉴스",
    "yonhapnews.co.kr": "연합뉴스",
    "kbs.co.kr": "KBS",
    "sbs.co.kr": "SBS",
    "mbc.co.kr": "MBC",
    "hani.co.kr": "한겨레",
    "hankookilbo.com": "한국일보",
    "khan.co.kr": "경향신문",
    "mt.co.kr": "머니투데이",
    "mk.co.kr": "매일경제",
    "hankyung.com": "한국경제",
    "news1.kr": "뉴스1",
    "newsis.com": "뉴시스",
    "ytn.co.kr": "YTN",
    "jtbc.co.kr": "JTBC",
    "tvchosun.com": "TV조선",
}

# 수법별 기본 설명 + 예방 포인트
METHOD_PROFILES = {
    "보이스피싱": {
        "how": "전화로 검찰·경찰·금융기관 직원을 사칭해 공포감을 조성한 뒤, 계좌이체·원격제어 앱 설치를 유도합니다.",
        "watch": "모르는 번호의 '수사 협조' 요청, 원격제어 앱 설치 요구는 즉시 거절하세요.",
    },
    "스미싱": {
        "how": "문자·메신저로 악성 링크나 가짜 앱 설치 주소를 보내 개인정보·금융정보를 탈취합니다.",
        "watch": "택배·검찰·정부 문자의 링크는 누르지 말고, 공식 앱·사이트로 직접 확인하세요.",
    },
    "큐싱": {
        "how": "QR코드를 스캔하게 해 가짜 사이트로 유도하거나 악성 앱 설치를 시도합니다.",
        "watch": "출처 불명의 QR코드는 스캔하지 말고, 결제·로그인은 공식 경로만 이용하세요.",
    },
    "로맨스스캠": {
        "how": "온라인에서 신뢰를 쌓은 뒤 투자·긴급 사정 등을 핑계로 금전을 요구합니다.",
        "watch": "만나지 못한 상대의 송금·가상자산 투자 권유는 사기로 의심하세요.",
    },
    "딥페이크": {
        "how": "AI로 합성한 얼굴·목소리로 지인·유명인·기관 관계자를 사칭해 신뢰를 획득합니다.",
        "watch": "영상·음성만 믿지 말고, 다른 연락 수단으로 본인 여부를 재확인하세요.",
    },
    "메신저피싱": {
        "how": "카카오톡 등 메신저에서 지인·가족을 사칭해 급전·상품권·계좌이체를 요구합니다.",
        "watch": "메신저 금전 요구는 전화로 직접 확인하세요. '지금 당장' 압박이 핵심 신호입니다.",
    },
    "몸캠피싱": {
        "how": "영상 통화·채팅 중 촬영·유포를 빌미로 협박해 금품을 요구합니다.",
        "watch": "협박이 오면 응하지 말고 증거를 보존한 채 경찰(112)에 신고하세요.",
    },
    "전세사기": {
        "how": "허위·중복 계약, 선순위 권리 미고지 등으로 보증금을 가로챕니다.",
        "watch": "등기·확정일자·전세보증 가입 여부를 계약 전 반드시 확인하세요.",
    },
    "기관사칭": {
        "how": "검찰·경찰·금감원·은행 등 공공·금융기관을 사칭해 개인정보와 돈을 요구합니다.",
        "watch": "기관은 전화로 계좌이체·현금 전달을 요구하지 않습니다.",
    },
    "금융기관 사칭": {
        "how": "금융감독원·은행·카드사 등 금융기관 직원을 사칭해 계좌·카드·송금·인증 정보를 요구합니다.",
        "watch": "금융기관은 전화·문자로 비밀번호·OTP·송금을 요구하지 않습니다. 공식 앱·창구로 확인하세요.",
    },
    "정부지원금 사기": {
        "how": "지원금·환급·보조금 지급을 미끼로 개인정보·수수료 입금을 유도합니다.",
        "watch": "정부 지원금은 문자 링크로 신청받지 않습니다. 공식 누리집에서 확인하세요.",
    },
    "카셰어링 사기": {
        "how": "카셰어링·차량 공유 명목으로 명의 대여·보증금·범칙금·수리비 등을 요구해 금전을 편취합니다.",
        "watch": "차량 공유·카셰어링 알바·명의 대여 제안은 범죄 연루·피해로 이어질 수 있습니다.",
    },
    "신종 사기": {
        "how": "기존 수법을 변형하거나 AI·신규 플랫폼을 악용해 피해자가 낯선 방식으로 금전·정보를 빼앗깁니다.",
        "watch": "처음 보는 연락·결제·인증 방식이면 일단 멈추고, 공식 기관·지인에게 별도로 확인하세요.",
    },
    "지인사칭": {
        "how": "가족·지인 번호를 도용하거나 메신저 계정을 탈취해 금전을 요구합니다.",
        "watch": "갑작스러운 금전 요청은 다른 번호로 재확인하세요.",
    },
}

# 파생 키워드(범죄 행위·수단)용 주의보 설명
ACTION_KEYWORD_PROFILES = {
    "편취": {
        "how": "피해자를 속여 계좌이체·송금·개인정보 입력 등으로 금전이나 정보를 빼앗습니다.",
        "watch": "모르는 연락·링크·앱 설치 요구에 금전·정보를 내주지 마세요.",
    },
    "사칭": {
        "how": "경찰·검찰·은행·지인 등을 흉내 내 연락해 공포감·긴박감을 조성한 뒤 돈이나 정보를 요구합니다.",
        "watch": "기관·지인 사칭 연락은 공식 번호·다른 경로로 본인 확인 후 대응하세요.",
    },
    "대포통장": {
        "how": "타인 명의 계좌로 피해금을 받아 인출책·전달책 등 여러 단계로 돈을 세탁·인출합니다.",
        "watch": "통장·카드 대여, 송금 대행 알바 제안은 모두 불법이며 범죄에 연루될 수 있습니다.",
    },
    "원격제어": {
        "how": "전화·문자로 원격제어 앱(팀뷰어 등) 설치를 유도해 휴대폰·PC 화면을 조작하며 금융 앱으로 송금합니다.",
        "watch": "모르는 연락의 앱 설치·화면 공유 요구는 즉시 거절하고 앱을 삭제하세요.",
    },
    "악성링크": {
        "how": "문자·메신저·이메일의 링크를 누르게 해 가짜 로그인·결제 페이지로 유도해 정보를 탈취합니다.",
        "watch": "출처 불명 링크는 누르지 말고, 공식 앱·사이트 주소를 직접 입력해 접속하세요.",
    },
    "악성앱": {
        "how": "가짜 앱·apk 설치를 유도해 금융·인증 정보를 훔치거나 원격으로 기기를 조작합니다.",
        "watch": "공식 스토어가 아닌 경로의 앱 설치 요구는 거절하세요.",
    },
    "계좌이체": {
        "how": "사칭·협박·긴급 상황을 연출해 즉시 계좌이체·송금을 요구합니다.",
        "watch": "'지금 당장' 송금을 재촉하면 사기일 가능성이 큽니다. 잠시 멈추고 확인하세요.",
    },
    "송금": {
        "how": "투자·로맨스·지인 사칭·기관 사칭 등을 빌미로 지속적으로 송금을 요구합니다.",
        "watch": "만난 적 없거나 확인되지 않은 상대에게 송금하지 마세요.",
    },
    "금전요구": {
        "how": "긴급 상황·수사·협박·관계 유지 등을 핑계로 현금·상품권·코인 송금을 반복 요구합니다.",
        "watch": "금전 요구가 나오면 연락을 끊고, 공식 기관·지인에게 별도로 확인하세요.",
    },
    "상품권": {
        "how": "수사 협조·대출·아르바이트 등을 미끼로 휴대폰 상품권 PIN 번호 전달을 요구합니다.",
        "watch": "상품권 번호를 문자·전화로 알려달라는 요구는 전형적인 피싱입니다.",
    },
    "리딩방": {
        "how": "카카오톡·텔레그램 등 단체 채팅방에서 유명인·전문가를 사칭해 종목·코인 매수를 유도합니다.",
        "watch": "원금 보장·확정 수익 리딩방·투자 권유는 사기로 의심하세요.",
    },
    "가상자산": {
        "how": "고수익 코인·거래소·지갑으로 송금을 유도한 뒤 출금을 막거나 가짜 수익을 보여 편취합니다.",
        "watch": "SNS·메신저의 코인 투자·송금 권유는 신중히 확인하세요.",
    },
    "명의도용": {
        "how": "개인정보·통장·인증수단을 탈취·매입해 대포통장·대출·통신 가입 등에 악용합니다.",
        "watch": "주민번호·통장·OTP·인증서를 요구하는 연락·사이트에 응하지 마세요.",
    },
    "협박": {
        "how": "영상·사진·개인정보 유출, 가족·수사 연루 등을 빌미로 금품 송금을 강요합니다.",
        "watch": "협박에 응하지 말고 112 신고 후 증거를 보존하세요.",
    },
    "유포": {
        "how": "촬영물·개인정보 공개를 협박하거나, 유포를 막는다며 돈을 요구합니다.",
        "watch": "협박성 유포 요구는 신고 대상이며, 돈을 내도 반복될 수 있습니다.",
    },
    "유인": {
        "how": "고수익·쉬운 돈·지원금·로맨스 등을 미끼로 연락·가입·송금·앱 설치를 유도합니다.",
        "watch": "지나치게 쉬운 돈벌이·지원금 제안은 의심부터 하세요.",
    },
    "갈취": {
        "how": "협박·공포·수사 연루 주장 등으로 피해자가 스스로 돈을 내게 만듭니다.",
        "watch": "공포를 이용한 긴급 송금 요구는 사칭 사기일 가능성이 큽니다.",
    },
    "인출책": {
        "how": "피해금이 입금된 계좌에서 현금·코인 등으로 인출해 조직에 전달하는 역할을 맡깁니다.",
        "watch": "송금·인출 대행 알바, 통장 대여 제안은 범죄 가담이 될 수 있습니다.",
    },
    "전달책": {
        "how": "인출된 현금·상품권·코인을 다음 단계로 전달해 추적을 어렵게 만드는 역할입니다.",
        "watch": "현금·상품권 전달 알바, 대리 수령 요청은 불법입니다.",
    },
    "OTP": {
        "how": "가짜 로그인·결제·수사 페이지에서 인증번호(OTP) 입력을 받아 계좌·앱을 탈취합니다.",
        "watch": "인증번호는 절대 남에게 알려주지 마세요. 기관·은행도 요구하지 않습니다.",
    },
    "인증번호": {
        "how": "문자·전화로 받은 인증번호를 알려달라고 요구해 금융·통신 계정을 장악합니다.",
        "watch": "인증번호 요구는 사기 신호입니다. 즉시 연락을 끊으세요.",
    },
    "팀뷰어": {
        "how": "원격제어 앱 설치 후 화면을 공유해 금융 앱으로 직접 송금·대출을 실행합니다.",
        "watch": "모르는 상대의 원격 앱 설치·화면 공유 요구는 거절하세요.",
    },
    "전화금융사기": {
        "how": "전화로 금융기관·수사기관을 사칭해 계좌·카드·대출 정보를 빼내거나 송금을 유도합니다.",
        "watch": "전화로 계좌·비밀번호·OTP를 묻는 경우는 모두 사기입니다.",
    },
}

ALERT_PROFILES = {**METHOD_PROFILES, **ACTION_KEYWORD_PROFILES}


def summarize_crime_from_news(top_crime: str, news_list: list[dict]) -> str:
    """해당 키워드가 포함된 기사에서 자주 언급되는 구체 범행 방식을 요약합니다."""
    matching = []
    for news in news_list:
        text = f"{news.get('title', '')} {news.get('description', '')}"
        keywords = news.get("keywords") or news.get("analysis", {}).get("keywords", [])
        if top_crime in text or top_crime in keywords:
            matching.append(news)

    if not matching:
        return ""

    tactic_counter: Counter = Counter()
    for news in matching[:25]:
        tactics = news.get("tactics") or news.get("analysis", {}).get("tactics", [])
        tactic_counter.update(tactics)

    if not tactic_counter:
        return ""

    top_tactics = [name for name, _ in tactic_counter.most_common(3)]
    return f"보도에서는 **{' / '.join(top_tactics)}** 방식이 함께 언급됩니다."


def select_tied_top_keywords(
    keyword_rank: list[tuple[str, int]],
) -> list[tuple[str, int]]:
    """1위와 언급 횟수가 같은 키워드를 모두 반환합니다."""
    if not keyword_rank:
        return []
    top_count = keyword_rank[0][1]
    return [(kw, cnt) for kw, cnt in keyword_rank if cnt == top_count]


def build_urgent_alert_info(
    top_crimes: list[str] | str,
    top_count: int,
    news_list: list[dict],
) -> dict:
    """긴급 주의보에 쓸 키워드·범행 진행 방식 문구를 만듭니다."""
    keywords = [top_crimes] if isinstance(top_crimes, str) else list(top_crimes)
    if not keywords:
        keywords = ["피싱"]

    how_parts: list[str] = []
    watch_parts: list[str] = []
    for crime in keywords:
        profile = ALERT_PROFILES.get(
            crime,
            {
                "how": "피싱·사기 피해를 유도하는 연락·링크·송금 요구가 최근 보도에서 반복되고 있습니다.",
                "watch": "금전·개인정보 요구, 링크 클릭·앱 설치 유도가 있으면 일단 중단하고 공식 경로로 확인하세요.",
            },
        )
        how_base = profile.get("how", "")
        news_hint = summarize_crime_from_news(crime, news_list)
        how_full = f"{how_base} {news_hint}".strip() if news_hint else how_base
        if len(keywords) > 1:
            how_parts.append(f"[{crime}] {how_full}")
            if profile.get("watch"):
                watch_parts.append(f"[{crime}] {profile['watch']}")
        else:
            how_parts.append(how_full)
            if profile.get("watch"):
                watch_parts.append(profile["watch"])

    return {
        "keyword": " · ".join(keywords),
        "keywords": keywords,
        "count": top_count,
        "how": how_parts[0] if how_parts else "",
        "how_full": "\n".join(how_parts),
        "watch": "\n".join(watch_parts),
    }





def render_naver_api_attribution() -> None:
    """네이버 OPEN API 검색 결과 표기 (이용약관 준수)."""
    st.caption(
        "📰 **네이버 OPEN API** 검색 결과 · 제목·요약 저작권은 각 언론사에 있습니다."
    )


def format_phishing_112_report_hint(keyword: str | list[str] | None) -> str:
    """키워드에 맞춘 112 신고 안내 문구."""
    if isinstance(keyword, list):
        labels = [k for k in keyword if k]
        label = " · ".join(labels) if labels else "피싱"
    else:
        label = (keyword or "").strip() or "피싱"
    return f"「{label}」 의심 시 즉시 112에 신고해 주세요."


def render_app_analysis_block(analysis: dict) -> None:
    """API 검색결과와 구분된 자체 범행 수법 분석 블록."""
    st.markdown('<div class="phishing-app-analysis-block"></div>', unsafe_allow_html=True)
    st.markdown(f"**🔎 범행 수법 분석:** {analysis['how_detail']}")
    report_hint = format_phishing_112_report_hint(
        analysis.get("primary") or (analysis.get("keywords") or [None])[0]
    )
    st.info(f"🛡️ 예방: {analysis['watch']} {report_hint}")


def render_phishing_alert_block(alert: dict) -> None:
    """피싱 주의보 — 키워드 링크 클릭 시 예방 포인트 아래 기사 목록으로 이동."""
    keywords = alert.get("keywords") or [alert["keyword"]]
    keywords = [kw for kw in keywords if kw]
    count = alert["count"]

    _link_nonce = int(st.session_state.get("moa_alert_link_nonce") or 1)
    link_parts = [
        (
            f'<a class="phishing-alert-keyword-link" '
            f'href="?alert_moa={quote(kw)}&n={_link_nonce}" '
            f'target="_self">{html.escape(kw)}</a>'
        )
        for kw in keywords
    ]
    keyword_html = " · ".join(link_parts)

    how_html = html.escape(alert["how_full"]).replace("\n", "<br>")
    watch_html = ""
    report_hint = format_phishing_112_report_hint(keywords)
    if alert.get("watch"):
        watch = html.escape(alert["watch"].strip()).replace("\n", "<br>")
        report_html = html.escape(report_hint)
        watch_html = (
            f'<div class="phishing-alert-watch"><strong>🛡️ 예방 포인트</strong><br>'
            f"{watch} {report_html}</div>"
        )
    else:
        watch_html = (
            f'<div class="phishing-alert-watch"><strong>🛡️ 예방 포인트</strong><br>'
            f"{html.escape(report_hint)}</div>"
        )

    guide_links_html = (
        '<div class="phishing-alert-guide-links">'
        '<a href="https://www.counterscam112.go.kr/main.do" '
        'target="_blank" rel="noopener noreferrer">피싱안심SOS</a>'
        '<span class="phishing-alert-guide-sep">·</span>'
        '<a href="https://www.counterscam112.go.kr/bbs009/board/boardList.do" '
        'target="_blank" rel="noopener noreferrer">피싱 시나리오</a>'
        '<span class="phishing-alert-guide-sep">·</span>'
        '<a href="https://www.counterscam112.go.kr/bbs010/board/boardList.do" '
        'target="_blank" rel="noopener noreferrer">상황별 조치방법</a>'
        "</div>"
    )

    how_section = (
        f'<div class="phishing-alert-how"><strong>🔎 범행 진행 방식</strong><br>{how_html}</div>'
        f"{watch_html}"
        f"{guide_links_html}"
    )

    st.markdown(
        f"""
        <div class="phishing-alert-hero" id="alert-stay-anchor">
          <div class="phishing-alert-badge">
            <span class="phishing-alert-pulse"></span>
            🚨 피싱 주의보 · LIVE
          </div>
          <div class="phishing-alert-label">최근 피싱범죄 주의 키워드</div>
          <div class="phishing-alert-kw-main">
            <div class="phishing-alert-keyword">{keyword_html}</div>
          </div>
          <div class="phishing-alert-count-wrap">
            <p class="phishing-alert-count">{count}회 언급</p>
          </div>
        </div>
        {how_section}
        <div id="alert-after-prevention"></div>
        """,
        unsafe_allow_html=True,
    )


def render_backseo_section_header(article_count: int) -> None:
    """피싱 범죄 백서 섹션 헤더."""
    count_html = (
        f'<a class="phishing-backseo-count" href="#method-analysis-section" '
        f'target="_self" rel="noopener">'
        f"📋 수법·사건 기사 {article_count}건</a>"
        if article_count
        else ""
    )
    st.markdown(
        f"""
        <div class="phishing-backseo-hero" id="method-stay-anchor">
          <div class="phishing-backseo-badge">
            <span class="phishing-backseo-pulse"></span>
            📋 수법 분석 및 예방
          </div>
          <div class="phishing-backseo-title">피싱 수법 Da Moa</div>
          <div class="phishing-backseo-sub">
            실제 피해·범행 사례가 확인된 기사만 찾아
            사칭·편취·계좌이체 등 구체적 수법과 예방법을 정리했습니다.
          </div>
          {count_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
    if article_count:
        components.html(
            """
            <script>
            (function () {
              const d = window.parent.document;
              const link = d.querySelector("a.phishing-backseo-count");
              if (!link || link.dataset.scrollBound === "1") return;
              link.dataset.scrollBound = "1";
              link.addEventListener("click", function (e) {
                e.preventDefault();
                e.stopPropagation();
                const el = d.getElementById("method-analysis-section");
                if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
              });
            })();
            </script>
            """,
            height=0,
        )


def render_moa_section_header() -> None:
    """Da Moa 섹션 헤더."""
    st.markdown(
        """
        <div class="phishing-moa-hero" id="moa-stay-anchor">
          <div class="phishing-moa-badge">
            <span class="phishing-moa-pulse"></span>
            🔍 키워드별 최신 기사
          </div>
          <div class="phishing-moa-title">최신 피싱 기사 Da Moa</div>
          <div class="phishing-moa-sub">
            궁금한 금융사기 유형을 고르면
            <strong>해당 키워드 최신 기사</strong>만 바로 불러옵니다.
          </div>
          <a class="phishing-moa-count" href="#moa-keyword-picker-section"
             target="_self" rel="noopener">👇 아래에서 키워드를 선택하세요</a>
        </div>
        """,
        unsafe_allow_html=True,
    )
    components.html(
        """
        <script>
        (function () {
          const d = window.parent.document;
          const w = window.parent;
          const link = d.querySelector("a.phishing-moa-count");
          if (!link || link.dataset.scrollBound === "1") return;
          link.dataset.scrollBound = "1";

          function fireClick(el) {
            if (!el) return;
            ["pointerdown", "mousedown", "mouseup", "click"].forEach(function (type) {
              el.dispatchEvent(
                new MouseEvent(type, {
                  bubbles: true,
                  cancelable: true,
                  view: w,
                })
              );
            });
          }

          function findMoaSelectbox() {
            const marker = d.getElementById("moa-keyword-select-marker");
            if (marker) {
              let n = marker.closest('[data-testid="stElementContainer"]');
              n = n ? n.nextElementSibling : null;
              for (let i = 0; i < 8 && n; i++) {
                const box = n.querySelector(
                  '[data-testid="stSelectbox"], .stSelectbox'
                );
                if (box) return box;
                n = n.nextElementSibling;
              }
            }
            const anchor = d.getElementById("moa-keyword-picker-section");
            if (anchor) {
              let n = anchor.closest('[data-testid="stElementContainer"]');
              n = n ? n.nextElementSibling : null;
              for (let i = 0; i < 8 && n; i++) {
                const box = n.querySelector(
                  '[data-testid="stSelectbox"], .stSelectbox'
                );
                if (box) return box;
                n = n.nextElementSibling;
              }
            }
            return d.querySelector('[data-testid="stSelectbox"], .stSelectbox');
          }

          function openDropdownArrow(box) {
            // 화살표(드롭다운 인디케이터) 우선 클릭 → 목록 현출
            const arrow =
              box.querySelector('[data-testid="stSelectboxChevron"]') ||
              box.querySelector('[data-baseweb="select"] svg') ||
              box.querySelector('[class*="dropdown"] svg') ||
              box.querySelector("svg");
            const combo =
              box.querySelector('[role="combobox"]') ||
              box.querySelector('[data-baseweb="select"] > div') ||
              box.querySelector('[data-baseweb="select"]') ||
              box.querySelector("input");

            if (arrow) {
              // svg 클릭이 안 먹으면 부모(화살표 영역) 클릭
              fireClick(arrow.closest("div") || arrow);
            }
            if (combo) {
              fireClick(combo);
              try {
                combo.focus();
              } catch (err) {}
              combo.dispatchEvent(
                new KeyboardEvent("keydown", {
                  key: "ArrowDown",
                  code: "ArrowDown",
                  keyCode: 40,
                  which: 40,
                  bubbles: true,
                  cancelable: true,
                })
              );
            }
          }

          function openMoaKeywordPicker() {
            const anchor = d.getElementById("moa-keyword-picker-section");
            if (anchor) {
              anchor.scrollIntoView({ behavior: "smooth", block: "center" });
            }
            // 스크롤 안정화 후 화살표 클릭으로 목록 열기 (재시도)
            var tries = 0;
            function attempt() {
              tries += 1;
              const box = findMoaSelectbox();
              if (box) {
                openDropdownArrow(box);
                return;
              }
              if (tries < 6) window.setTimeout(attempt, 120);
            }
            window.setTimeout(attempt, 280);
          }

          link.addEventListener("click", function (e) {
            e.preventDefault();
            e.stopPropagation();
            openMoaKeywordPicker();
          });
        })();
        </script>
        """,
        height=0,
    )


# 기사 본문에서 구체적 범행 수단을 찾는 규칙
# - strong: 단독으로도 인정 (고유·강한 단서)
# - combos: (그룹A 중 1개) + (그룹B 중 1개) 동시 등장 시 인정
# - types: 호환되는 피싱 유형 (비어 있으면 모든 유형)
MODUS_RULES: list[dict] = [
    {
        "label": "금융기관 사칭",
        "strong": ("금감원", "금융감독원", "은행 직원", "카드사 직원"),
        "combos": (
            (("금융기관", "은행", "카드사", "금감원", "금융감독"), ("사칭", "사칭해", "행세", "직원인 척")),
        ),
        "types": {
            "보이스피싱",
            "금융기관 사칭",
            "기관사칭",
            "스미싱",
            "메신저피싱",
            "전화금융사기",
        },
    },
    {
        "label": "검찰·경찰 등 수사기관 사칭",
        "strong": ("체포영장", "검찰 사칭", "경찰 사칭"),
        "combos": (
            (("검찰", "경찰", "수사관", "경찰청"), ("사칭", "사칭해", "행세", "공조", "수사")),
        ),
        "types": {
            "보이스피싱",
            "기관사칭",
            "메신저피싱",
            "스미싱",
            "전화금융사기",
        },
    },
    {
        "label": "가족·지인 사칭 급전 요구",
        "strong": ("폰 고장", "휴대폰이 고장"),
        "combos": (
            (("가족", "지인", "아들", "딸", "엄마", "아빠"), ("급전", "돈", "송금", "이체", "빌려")),
        ),
        "types": {"메신저피싱", "지인사칭", "보이스피싱"},
    },
    {
        "label": "악성 문자·링크 클릭 유도",
        "strong": ("악성앱", "악성 링크", "악성링크", "설치 유도"),
        "combos": (
            (("문자", "메시지", "SMS"), ("링크", "URL", "클릭", "접속")),
            (("링크", "URL"), ("개인정보", "로그인", "결제", "인증")),
        ),
        "types": {"스미싱", "큐싱", "보이스피싱", "정부지원금 사기", "메신저피싱"},
    },
    {
        "label": "QR코드 스캔 유도",
        "strong": ("큐싱",),
        "combos": ((("QR", "큐알", "큐아르"), ("스캔", "촬영", "인식", "결제")),),
        "types": {"큐싱", "스미싱"},
    },
    {
        "label": "메신저(카톡 등)로 금전·상품권 요구",
        "strong": ("상품권", "문화상품권", "구글기프트"),
        "combos": (
            (("카카오톡", "카톡", "메신저", "텔레그램"), ("송금", "이체", "돈", "급전", "상품권", "쿠폰")),
        ),
        "types": {"메신저피싱", "몸캠피싱", "로맨스스캠", "지인사칭"},
    },
    {
        "label": "원격제어 앱 설치 요구",
        "strong": ("팀뷰어", "AnyDesk", "TeamViewer", "원격제어"),
        "combos": (
            (("원격", "원격제어"), ("설치", "앱", "화면공유", "화면 공유", "어플")),
        ),
        "types": {
            "보이스피싱",
            "기관사칭",
            "금융기관 사칭",
            "전화금융사기",
        },
    },
    {
        "label": "고수익 투자·리딩방 유인",
        "strong": ("리딩방", "주식 리딩", "원금 보장"),
        "combos": (
            (("투자", "리딩", "코인", "가상자산"), ("수익", "수익률", "고수익", "보장", "단타")),
        ),
        "types": {"로맨스스캠", "리딩방", "고수익 투자", "신종 사기"},
    },
    {
        "label": "영상·딥페이크 협박·사칭",
        "strong": ("딥페이크", "몸캠", "영상 유포"),
        "combos": (
            (("영상", "딥페이크", "합성"), ("협박", "유포", "유출", "사칭")),
        ),
        "types": {"딥페이크", "몸캠피싱"},
    },
    {
        "label": "지원금·환급 미끼",
        "strong": ("재난지원금", "지원금 신청"),
        "combos": (
            (("지원금", "환급", "보조금", "재난지원"), ("링크", "신청", "클릭", "문자", "수수료")),
        ),
        "types": {"정부지원금 사기", "스미싱", "보이스피싱"},
    },
    {
        "label": "렌탈·렌터카·카셰어링 명의 대여 후 미반납·추가금 요구",
        "strong": ("카셰어링", "명의 대여"),
        "combos": (
            (("렌탈", "렌터카", "카셰어링", "차량 공유"), ("보증금", "범칙금", "미반납", "추가금", "연장")),
        ),
        "types": {"신종 사기", "카셰어링 사기", "휴대폰 렌탈 사기"},
    },
    {
        "label": "신종·변형 수법 언급",
        "strong": ("신종수법", "신종 사기", "변형 수법"),
        "combos": (),
        "types": set(),
    },
]


def get_naver_credentials():
    try:
        client_id = st.secrets["NAVER_CLIENT_ID"]
        client_secret = st.secrets["NAVER_CLIENT_SECRET"]
    except Exception:
        return None, None

    if (
        not client_id
        or not client_secret
        or "your_client" in str(client_id)
        or "your_client" in str(client_secret)
    ):
        return None, None
    return client_id, client_secret


def format_naver_search_error(query: str, exc: requests.HTTPError) -> str:
    status = exc.response.status_code if exc.response is not None else "?"
    if status == 429:
        return (
            f"「{query}」 일일 API 호출 한도 초과 (HTTP 429). "
            "네이버 개발자센터 할당량을 확인하거나 내일 0시 이후 다시 시도하세요."
        )
    if status in (401, 403):
        return f"「{query}」 API 인증 오류 (HTTP {status}) — Client ID/Secret을 확인하세요."
    if status >= 500:
        return f"「{query}」 네이버 서버 일시 오류 (HTTP {status})"
    return f"「{query}」 검색 실패 (HTTP {status})"


def clean_html_text(text: str) -> str:
    text = re.sub(r"<.*?>", "", text or "")
    return (
        text.replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .strip()
    )


def extract_press_name(origin_link: str) -> str:
    if not origin_link:
        return "관련 언론사"
    host = urlparse(origin_link).netloc.lower().removeprefix("www.")
    for domain, name in PRESS_MAP.items():
        if domain in host:
            return name
    return host or "관련 언론사"


def contains_excluded(text: str) -> bool:
    """포상·홍보·대회·시책 등 비사례 기사 여부."""
    if any(word in text for word in EXCLUDE_KEYWORDS):
        return True
    for group_a, group_b in EXCLUDE_COMBO_RULES:
        if any(a in text for a in group_a) and any(b in text for b in group_b):
            return True
    return False


CRIME_CASE_NARRATIVE_WORDS = (
    "검거",
    "송치",
    "구속",
    "체포",
    "피의자",
    "용의자",
    "일당",
    "조직",
    "당했다",
    "당해",
    "당한",
    "속았",
    "속아",
    "속였",
    "편취",
    "갈취",
    "탈취",
    "적발",
    "기소",
    "A씨",
    "B씨",
)

PROMO_TITLE_HINTS = (
    "캠페인",
    "교육 실시",
    "교육실시",
    "협약",
    "MOU",
    "홍보",
    "설명회",
    "간담회",
    "예방",
    "당부",
    "추진",
    "나서",
    "동참",
    "앞장",
    "체험",
    "인식",
)


def has_crime_case_narrative(text: str) -> bool:
    """실제 사건·수사 보도 (통계·홍보 문맥의 '피해'와 구분)."""
    return any(word in text for word in CRIME_CASE_NARRATIVE_WORDS)


def has_promo_activity_context(text: str) -> bool:
    """홍보·교육·협약·캠페인 등 행사성 맥락."""
    if contains_excluded(text):
        return True
    activity = (
        "홍보",
        "캠페인",
        "교육",
        "협약",
        "설명회",
        "간담회",
        "체험",
        "행사",
        "개최",
        "MOU",
        "맞손",
        "워크숍",
        "세미나",
        "포럼",
    )
    if not any(a in text for a in activity):
        return False
    purpose = ("예방", "근절", "인식", "당부", "주의", "대응", "협력", "추진", "홍보")
    if any(p in text for p in purpose):
        return True
    return any(a in text for a in ("협약", "MOU", "캠페인", "설명회", "교육", "홍보"))


def is_promo_title_article(title: str, description: str = "") -> bool:
    """제목이 홍보·교육·협약 행사인데 사건·수사 표현이 없으면 제외."""
    title = title.strip()
    if not any(hint in title for hint in PROMO_TITLE_HINTS):
        return False
    return not has_crime_case_narrative(f"{title} {description}")


POLICE_STATION_TITLE_PATTERN = re.compile(
    r"[\uac00-\ud7a3]{2,10}경찰서|[\uac00-\ud7a3]{2,10}\s*경찰"
)


def is_police_station_promo_article(title: str, description: str = "") -> bool:
    """제목에 ○○경찰서·○○ 경찰이 있으면 제외 (제목에 검거·송치 등 있으면 유지)."""
    title = title.strip()
    if not POLICE_STATION_TITLE_PATTERN.search(title):
        return False
    if has_crime_case_narrative(title):
        return False
    return True


def is_alert_promo_excluded_article(
    title: str, description: str = "", link: str = ""
) -> bool:
    """피싱 주의보용 — 홍보·표창·협약·예방교육·예능·기고만 제외 (실제사례 필터 없음)."""
    combined = f"{title} {description}"
    if contains_excluded(combined):
        return True
    if has_promo_activity_context(combined):
        return True
    if any(marker in combined for marker in PROMO_POLICY_MARKERS):
        return True
    if is_promo_title_article(title, description):
        return True
    if is_police_station_promo_article(title, description):
        return True
    if is_prevention_advice_article(title, description):
        return True
    if is_entertainment_article(combined):
        return True
    if is_editorial_or_opinion_article(title, description, link):
        return True
    return False


# 실제 피해·범행 사례 신호
ACTUAL_CASE_SIGNALS = [
    "피해",
    "피해자",
    "피해액",
    "피해 금액",
    "피해금",
    "피해 규모",
    "당했다",
    "당해",
    "당한",
    "당함",
    "속았",
    "속아",
    "속였",
    "속임",
    "속게",
    "편취",
    "갈취",
    "탈취",
    "빼앗",
    "넘겼",
    "넘기",
    "송금",
    "이체",
    "출금",
    "인출",
    "입금",
    "잃었",
    "손실",
    "사례",
    "발생",
    "접수",
    "신고",
    "신고했다",
    "신고해",
    "만원",
    "천만",
    "수천만",
    "억원",
    "수억",
    "범행",
    "사칭당",
    "협박받",
    "요구받",
    "씨가",
    "씨는",
    "씨(",
    "A씨",
    "B씨",
]

PROMO_POLICY_MARKERS = (
    "대회",
    "공모전",
    "UCC",
    "시상",
    "시상식",
    "홍보 활동",
    "홍보활동",
    "홍보 행사",
    "홍보행사",
    "시책",
    "개최",
    "캠페인",
    "포럼",
    "설명회",
    "세미나",
    "기술 개발",
    "신기술",
    "탐지 기술",
    "차단 기술",
    "대응 기술",
    "체험 행사",
    "체험행사",
    "박람회",
)

# 실제 피해·편취가 확인된 사례 신호 (통계·예방·행사 기사와 구분)
VICTIM_CONFIRMED_WORDS = (
    "피해자",
    "피해액",
    "피해 금액",
    "피해금",
    "피해 규모",
    "편취",
    "갈취",
    "탈취",
    "당했다",
    "당해",
    "당한",
    "속았",
    "속아",
    "속였",
    "넘겼",
    "넘기",
    "잃었",
    "손실",
    "A씨",
    "B씨",
    "C씨",
    "○○씨",
)

NON_VICTIM_CONTEXT_PHRASES = (
    "기술 개발",
    "신기술",
    "AI 기술",
    "AI기술",
    "차단 기술",
    "탐지 기술",
    "대응 기술",
    "기술을 활용",
    "기술로",
    "행사 개최",
    "행사를",
    "행사가",
    "행사는",
    "행사에",
    "행사로",
    "체험 행사",
    "체험행사",
    "교육 프로그램",
    "교육프로그램",
    "예방 교육",
    "예방교육",
    "인식 제고",
    "인식제고",
    "대응 방안",
    "대응방안",
    "체험부스",
    "홍보부스",
    "웹예능",
    "web예능",
    "웹 예능",
    "예능 프로그램",
    "연예 프로그램",
    "OTT 오리지널",
    "유튜브 채널",
    "출연진",
    "첫 방송",
    "방송 예정",
)

NON_VICTIM_CONTEXT_COMBOS = [
    (("기술",), ("개발", "도입", "활용", "적용", "공개", "선보", "강화", "연구")),
    (("행사",), ("개최", "열", "진행", "마련", "연", "개막", "동", "참여", "성료")),
    (("피해",), ("예방", "줄", "막", "방지", "경감")),
]


def has_confirmed_victim_evidence(text: str) -> bool:
    """피해·편취 등 실제 사례가 확인된 표현이 있는지."""
    if any(word in text for word in VICTIM_CONFIRMED_WORDS):
        return True
    if any(word in text for word in ("송금", "이체", "출금", "인출")) and any(
        word in text
        for word in ("피해", "당", "속", "편취", "갈취", "억원", "만원", "천만")
    ):
        return True
    if re.search(r"\d+[억만천]?원", text) and any(
        word in text for word in ("피해", "편취", "갈취", "탈취", "송금", "이체", "속")
    ):
        return True
    return False


SURGE_FRAUD_MARKERS = ("기승", "급증", "급증세", "늘어", "증가", "확산", "고조", "늘고")
SURGE_CONTEXT_WORDS = (
    "피해",
    "수법",
    "범행",
    "사례",
    "발생",
    "주의",
    "경보",
    "피해자",
    "피의자",
    "검거",
    "적발",
    "신종",
)


def is_phishing_surge_article(text: str) -> bool:
    """피싱·금융사기 등과 함께 기승·급증이 언급된 보도."""
    if not any(marker in text for marker in SURGE_FRAUD_MARKERS):
        return False
    fraud_terms = PHISHING_RELATED_TERMS | FINANCIAL_FRAUD_TERMS | {"사기", "보이스", "피해"}
    return any(term in text for term in fraud_terms)


def qualifies_as_case_or_surge_report(text: str) -> bool:
    """피해 사례 확인 또는 피싱·사기 기승 보도."""
    if has_confirmed_victim_evidence(text):
        return True
    if is_phishing_surge_article(text):
        return any(word in text for word in SURGE_CONTEXT_WORDS)
    return False


def is_entertainment_article(text: str) -> bool:
    """예능·웹예능·방송 콘텐츠 등 범죄 사례 보도가 아닌 기사."""
    compact = text.replace(" ", "").lower()
    if any(token in compact for token in ("웹예능", "web예능", "webvariety")):
        return True

    program_signals = (
        "웹예능",
        "web예능",
        "웹 예능",
        "예능 프로그램",
        "연예 프로그램",
        "OTT",
        "넷플릭스",
        "티빙",
        "웨이브",
        "쿠팡플레이",
        "디즈니+",
        "에피소드",
        "시즌",
        "출연진",
        "첫 방송",
        "방송 예정",
        "조회수",
        "구독자",
        "유튜브 채널",
        "오리지널 시리즈",
        "오리지널",
    )
    if any(signal in text for signal in program_signals):
        return True

    soft_markers = (
        "예능",
        "출연",
        "방송",
        "유튜브",
        "유튜버",
        "크리에이터",
        "콘텐츠",
        "연예인",
        "인플루언서",
        "방영",
        "런칭",
    )
    if any(marker in text for marker in soft_markers):
        return not has_confirmed_victim_evidence(text)
    return False


def is_non_victim_context_article(text: str) -> bool:
    """예방 기술·행사·교육 등 실제 피해 사례가 아닌 맥락."""
    if is_entertainment_article(text):
        return True
    if has_promo_activity_context(text) and not has_crime_case_narrative(text):
        return True
    if has_confirmed_victim_evidence(text):
        if has_promo_activity_context(text) and not has_crime_case_narrative(text):
            return True
        return False
    if any(phrase in text for phrase in NON_VICTIM_CONTEXT_PHRASES):
        return True
    for group_a, group_b in NON_VICTIM_CONTEXT_COMBOS:
        if any(a in text for a in group_a) and any(b in text for b in group_b):
            return True
    if ("행사" in text or "기술" in text) and any(
        word in text for word in ("개최", "개발", "교육", "캠페인", "홍보", "예방", "체험")
    ):
        return True
    return False


def count_actual_case_signals(text: str) -> int:
    return sum(1 for word in ACTUAL_CASE_SIGNALS if word in text)


def is_promo_or_policy_article(text: str) -> bool:
    """대회·홍보·시책 추진 등 실제 사례가 아닌 기사."""
    if contains_excluded(text):
        return True
    if has_promo_activity_context(text) and not has_crime_case_narrative(text):
        return True
    if is_non_victim_context_article(text):
        return True

    case_hits = count_actual_case_signals(text)
    promo_hits = sum(1 for marker in PROMO_POLICY_MARKERS if marker in text)

    if not has_crime_case_narrative(text) and promo_hits >= 1:
        return True

    if any(word in text for word in ("공모전", "UCC", "경진대회", "콘테스트")):
        return True
    if "행사" in text and not has_confirmed_victim_evidence(text):
        return True
    if "기술" in text and not has_confirmed_victim_evidence(text) and any(
        word in text for word in ("개발", "도입", "활용", "탐지", "차단", "대응")
    ):
        return True
    if "대회" in text and case_hits < 1:
        return True
    if "시책" in text and "추진" in text and case_hits < 2:
        return True
    if promo_hits >= 2 and case_hits < 2:
        return True
    if "당부" in text and case_hits < 1 and not any(
        w in text for w in ("편취", "피해", "속", "송금", "이체", "사칭")
    ):
        return True
    return False


PREVENTION_ADVICE_TITLE_HINTS = (
    "아는 만큼",
    "막는",
    "막으",
    "예방법",
    "예방 하",
    "예방하",
    "대처법",
    "대응법",
    "주의법",
    "피하는",
    "이렇게 막",
    "알아두",
    "알아야",
    "알면",
    "조심",
    "각별",
    "당부",
    "유의",
)


def is_prevention_advice_article(title: str, description: str = "") -> bool:
    """「아는 만큼 막는 ○○」 등 예방·대처 안내·칼럼 (본문 사례 인용 있어도 제외)."""
    title = title.strip()
    if not any(hint in title for hint in PREVENTION_ADVICE_TITLE_HINTS):
        return False
    crime_in_title = any(
        w in title
        for w in (
            "검거",
            "편취",
            "당했다",
            "당해",
            "피해액",
            "일당",
            "적발",
            "송치",
            "구속",
            "체포",
            "피의자",
        )
    )
    return not crime_in_title


def is_actual_case_article(
    title: str, description: str, keywords: list[str], tactics: list[str]
) -> bool:
    """실제 발생한 피해·범행 사례가 드러나는 기사."""
    combined = f"{title} {description}"
    if is_prevention_advice_article(title, description):
        return False
    if is_promo_title_article(title, description):
        return False
    if is_police_station_promo_article(title, description):
        return False
    if is_promo_or_policy_article(combined):
        return False
    if is_non_victim_context_article(combined):
        return False
    if not qualifies_as_case_or_surge_report(combined):
        return False

    if not is_phishing_related_article(title, description, keywords):
        return False
    if not tactics and not keywords and count_substance_hits(combined) < 2:
        return False
    return True


# 범행·수법·수사·피해 등 '사건성' 신호 (단순 키워드 언급과 구분)
CRIME_SUBSTANCE_KEYWORDS = [
    "수법",
    "범행",
    "사칭",
    "편취",
    "갈취",
    "유인",
    "검거",
    "송치",
    "구속",
    "피해자",
    "피의자",
    "용의자",
    "일당",
    "조직",
    "이체",
    "송금",
    "원격",
    "악성",
    "링크",
    "협박",
    "유포",
    "미끼",
    "유도",
    "대포통장",
    "인출",
    "피해액",
    "기소",
    "구형",
    "징역",
    "기승",
    "신종수법",
    "범행수법",
    "가짜 사이트",
    "가짜 앱",
    "OTP",
    "인증번호",
    "통화",
    "전화로",
    "문자로",
    "카톡으로",
]

TITLE_CRIME_HINTS = [
    "피싱",
    "스미싱",
    "큐싱",
    "스캠",
    "사기",
    "사칭",
    "편취",
    "검거",
    "송치",
    "구속",
    "수법",
    "피해",
    "렌탈",
    "렌터카",
    "카셰어링",
    "기승",
    "급증",
]


def count_substance_hits(text: str) -> int:
    return sum(1 for word in CRIME_SUBSTANCE_KEYWORDS if word in text)


def has_crime_type_in_title(title: str) -> bool:
    if any(kw in title for kw in PHISHING_KEYWORDS):
        return True
    return any(hint in title for hint in TITLE_CRIME_HINTS)


def is_method_focused_article(
    title: str, description: str, keywords: list[str], tactics: list[str]
) -> bool:
    """
    '보이스피싱' 등 단어만 스치듯 나온 기사는 제외하고,
    범행 수법·피해·수사 내용이 드러나는 기사만 통과시킵니다.
    """
    if is_editorial_or_opinion_article(title, description, ""):
        return False
    if is_prevention_advice_article(title, description):
        return False
    if is_promo_title_article(title, description):
        return False
    if is_police_station_promo_article(title, description):
        return False
    combined = f"{title} {description}"
    if is_promo_or_policy_article(combined):
        return False
    if is_non_victim_context_article(combined):
        return False
    if not qualifies_as_case_or_surge_report(combined):
        return False

    substance = count_substance_hits(combined)
    title_focused = has_crime_type_in_title(title)
    method_words = any(
        w in combined
        for w in ("수법", "범행", "사칭", "유인", "편취", "갈취", "미끼", "유도", "기승", "급증")
    )

    # 피싱 유형 키워드가 본문에 전혀 없으면 제외
    generic_type = any(
        w in combined
        for w in (
            "보이스피싱",
            "스미싱",
            "메신저피싱",
            "몸캠피싱",
            "피싱",
            "큐싱",
            "로맨스스캠",
            "신종 사기",
            "금융기관 사칭",
            "휴대폰 렌탈 사기",
            "카셰어링 사기",
        )
    )
    if not keywords and not generic_type:
        return False

    # 수법/사건 신호가 약하면 제외 (단순 언급 기사)
    if not tactics and substance < 2 and not method_words:
        return False

    # 제목이 범죄와 무관하고 본문에만 약하게 언급 → 제외
    if not title_focused and substance < 3 and not tactics:
        return False

    # 키워드도 없고 제목 사건성도 약하면 제외
    if not keywords and not (title_focused and (tactics or substance >= 2)):
        return False

    return True


# Da Moa 범죄기사 — 제목 기준 (예방·주의 당부성 기사 축소)
MOA_CRIME_INVESTIGATION_MARKERS = (
    "검거",
    "검거된",
    "검거돼",
    "붙잡",
    "송치",
    "구속",
    "체포",
    "적발",
    "기소",
    "재판",
    "선고",
    "징역",
    "피의자",
    "용의자",
    "일당",
)
MOA_CRIME_METHOD_MARKERS = (
    "편취",
    "편취한",
    "수법",
    "기승",
    "급증",
)
MOA_CRIME_CASE_SIGNALS = (
    "일당",
    "피의자",
    "용의자",
    "속아",
    "속았",
    "억원",
    "수억",
    "만원",
    "피해액",
    "조직",
)


def _moa_text_has_keyword(text: str, keyword: str) -> bool:
    """선택 키워드가 제목·요약에 포함되는지 (공백 차이 허용)."""
    if keyword in text:
        return True
    return keyword.replace(" ", "") in text.replace(" ", "")


def is_moa_keyword_related(title: str, description: str, keyword: str) -> bool:
    """키워드 검색 — 선택 키워드와 연관된 기사 (넓게)."""
    combined = f"{title} {description}"
    return _moa_text_has_keyword(combined, keyword.strip())


def is_moa_crime_only_article(
    title: str, description: str = "", keywords: list[str] | None = None
) -> bool:
    """Da Moa — 범죄기사(제목).

    1) 수사·사법 마커 1개 이상, 또는
    2) 범행 마커 + 사건 신호 동시
    """
    t = title.strip()
    if not t:
        return False
    if any(marker in t for marker in MOA_CRIME_INVESTIGATION_MARKERS):
        return True
    has_method = any(marker in t for marker in MOA_CRIME_METHOD_MARKERS)
    has_case = any(signal in t for signal in MOA_CRIME_CASE_SIGNALS)
    return has_method and has_case


def normalize_article_title(title: str) -> str:
    """중복 판별용 제목 정규화 (공백·구두점·말미 태그 차이 무시)."""
    t = (title or "").strip().lower()
    t = re.sub(r"<.*?>", "", t)
    for a, b in (
        ("“", '"'),
        ("”", '"'),
        ("‘", "'"),
        ("’", "'"),
        ("…", "..."),
        ("·", ""),
        ("・", ""),
        ("－", "-"),
        ("—", "-"),
        ("–", "-"),
    ):
        t = t.replace(a, b)
    # 말미 부가 표기 제거: (종합), [포토], 【속보】 등
    t = re.sub(r"[\(（\[【][^\)）\]】]{0,20}[\)）\]】]\s*$", "", t)
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[\"'.,，。!！?？~\-_/\\|\[\]()（）【】「」『』…]", "", t)
    return t


def dedupe_articles_by_title(articles: list[dict]) -> list[dict]:
    """동일·유사 제목 기사는 목록에 한 번만 남깁니다."""
    seen: set[str] = set()
    unique: list[dict] = []
    for article in articles:
        key = normalize_article_title(article.get("title", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(article)
    return unique


def relevance_score(
    title: str, keywords: list[str], tactics: list[str], description: str
) -> int:
    combined = f"{title} {description}"
    score = len(tactics) * 4 + count_substance_hits(combined)
    if has_crime_type_in_title(title):
        score += 5
    if keywords:
        score += 2 * len(keywords)
    if any(w in combined for w in ("수법", "범행", "사칭", "편취")):
        score += 3
    if is_phishing_surge_article(combined):
        score += 4
    return score


def match_phishing_keywords(text: str) -> list[str]:
    found = []
    remaining = text
    for kw in PHISHING_KEYWORDS:
        if kw in remaining:
            found.append(kw)
            remaining = remaining.replace(kw, " " * len(kw))
    return found


# 뉴스 본문 키워드 스크랩용 불용어·추적 표현
KEYWORD_STOPWORDS = {
    "기자", "뉴스", "사진", "영상", "오늘", "지난", "최근", "관련", "따르면",
    "있다", "있다며", "이라고", "했으며", "했다", "한다", "하며", "위한",
    "통해", "대해", "대해선", "대한", "경우", "가운데", "이후", "이전",
    "이날", "이번", "이들", "이상", "이하", "같은", "다른", "모든", "일부",
    "경찰", "검찰", "기자입니다", "습니다", "입니다", "것으로", "것으로",
    "밝혔다", "전했다", "말했다", "설명했다", "강조했다", "나섰다",
    "기술", "행사", "개최", "개발", "박람회", "세미나", "설명회",
    "예능", "웹예능", "출연", "방송", "유튜브", "유튜버", "크리에이터", "콘텐츠",
    "지난해", "올해", "내일", "어제", "시간", "오전", "오후", "새벽",
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
    "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주",
    "우리", "그들", "이것", "그것", "여기", "거기", "어디", "무엇",
    "그리고", "그러나", "하지만", "또한", "또", "및", "등", "등등",
    "위해", "따라", "따라며", "에서", "으로", "로서", "로써", "부터",
    "까지", "이나", "또는", "혹은", "같은", "같은날",
}

# 기관·일반 표현 (범죄 수법이 아니므로 상위 키워드·재검색에서 제외)
NON_CRIME_EXCLUDE_KEYWORDS = {
    "보이스피싱",
    "보이스",
    "피싱",
    "금융사기",
    "금융",
    "금융기관",
    "저축은행",
    "카드사",
    "보험",
    "보험사",
    "증권",
    "증권사",
    "우체국",
    "카카오뱅크",
    "토스",
    "국민은행",
    "신한은행",
    "우리은행",
    "하나은행",
    "농협",
    "기업은행",
    "새마을금고",
    "신용협동조합",
    "정부",
    "지자체",
    "주민",
    "시민",
    "사회",
    "경제",
    "시장",
    "업계",
    "기술",
    "행사",
    "개최",
    "개발",
    "박람회",
    "예능",
    "웹예능",
    "출연",
    "방송",
    "유튜브",
    "유튜버",
    "크리에이터",
    "콘텐츠",
    "에피소드",
}

# 본문에서 따로 집계할 범죄·수단 관련 표현 (긴 것 우선)
TRACKED_PHRASE_KEYWORDS = PHISHING_KEYWORDS + [
    "대포통장",
    "원격제어",
    "악성링크",
    "악성앱",
    "가짜사이트",
    "계좌이체",
    "금전요구",
    "상품권",
    "검거",
    "송치",
    "구속",
    "편취",
    "사칭",
    "피해자",
    "피의자",
    "일당",
    "조직",
    "수법",
    "범행",
    "이체",
    "송금",
    "협박",
    "유포",
    "리딩방",
    "가상자산",
    "OTP",
    "인출책",
    "전달책",
    "콜센터",
    "공작원",
    "유인",
    "갈취",
    "미끼",
    "악성",
    "기소",
    "구형",
    "징역",
    "체포",
    "수사",
    "단속",
    "적발",
    "기승",
    "신종",
    "딥페이크",
]

# 수사·재판·피해 규모 등 '범죄 행위'가 아닌 표현 (파생 키워드·재검색에서 제외)
INVESTIGATION_META_EXCLUDE_KEYWORDS = {
    "검거",
    "검거됐",
    "검거했다",
    "송치",
    "송치됐",
    "구속",
    "구속영장",
    "불구속",
    "기소",
    "구형",
    "징역",
    "체포",
    "체포영장",
    "수사",
    "수사 중",
    "수사중",
    "수사팀",
    "수사본부",
    "단속",
    "적발",
    "자수",
    "혐의",
    "의혹",
    "재판",
    "판결",
    "유죄",
    "무죄",
    "집행유예",
    "수법",
    "범행",
    "범행수법",
    "신종수법",
    "피해자",
    "피의자",
    "용의자",
    "피해액",
    "피해 규모",
    "피해금",
    "일당",
    "조직",
    "총책",
    "두목",
    "부두목",
    "기승",
    "신종",
    "사기",  # 단독 표현 (복합 수법명은 PHISHING_KEYWORDS에 유지)
    "경찰",
    "검찰",
    "경찰청",
    "검찰청",
    "수사관",
    "형사",
    "고발",
    "신고",
    "접수",
}

# 행위·수법 유형 — 재검색 키워드 우선순위 상위
HIGH_PRIORITY_ACTION_KEYWORDS = {
    "정부지원금 사기",
    "카셰어링 사기",
    "신종 사기",
    "로맨스스캠",
    "메신저피싱",
    "몸캠피싱",
    "금융기관 사칭",
    "기관사칭",
    "지인사칭",
    "딥페이크",
    "스미싱",
    "큐싱",
}

# 구체적 범죄 행위·수단 — 재검색 키워드 우선순위 중위
MEDIUM_PRIORITY_ACTION_KEYWORDS = {
    "계좌이체",
    "편취",
    "대포통장",
    "원격제어",
    "악성링크",
    "악성앱",
    "가짜사이트",
    "가짜 사이트",
    "가짜 앱",
    "금전요구",
    "상품권",
    "송금",
    "이체",
    "협박",
    "유포",
    "유포협박",
    "리딩방",
    "가상자산",
    "명의도용",
    "전화금융사기",
    "OTP",
    "인증번호",
    "팀뷰어",
    "인출책",
    "전달책",
    "콜센터",
    "공작원",
    "유인",
    "갈취",
    "미끼",
}

# 파생 키워드·주의보에서 제외할 포괄 행위 표현 (기관사칭·스미싱 등 구체 수법으로 대체)
GENERIC_DERIVED_KEYWORD_EXCLUDE = {
    "사칭",
}

# 피싱 검색 결과에서 파생 키워드 Top10 — 실제 범죄 행위·수단만 허용
# (보이스피싱은 너무 포괄적이라 제외 → 구체 수법·행위 키워드 위주)
DERIVED_KEYWORD_ALLOWLIST = {
    *(kw for kw in PHISHING_KEYWORDS if kw not in {"보이스피싱"}),
    "대포통장",
    "원격제어",
    "악성링크",
    "악성앱",
    "가짜사이트",
    "가짜 사이트",
    "가짜 앱",
    "계좌이체",
    "금전요구",
    "상품권",
    "편취",
    "이체",
    "송금",
    "협박",
    "유포",
    "유포협박",
    "리딩방",
    "가상자산",
    "OTP",
    "인증번호",
    "인출책",
    "전달책",
    "콜센터",
    "공작원",
    "유인",
    "갈취",
    "미끼",
    "명의도용",
    "전화금융사기",
    "팀뷰어",
}

# 피싱·사기 전체 수집용 시드 검색어
PHISHING_SEED_QUERIES = (
    "피싱",
    "보이스피싱",
    "스미싱",
    "큐싱",
    "메신저피싱",
    "몸캠피싱",
    "금융기관 사칭",
    "기관사칭",
    "지인사칭",
    "리딩방",
    "고수익 투자",
    "로맨스스캠",
    "딥페이크",
    "정부지원금 사기",
    "신종 사기",
    "전화금융사기",
)
# Da Moa 선택용 — 전세사기는 자동 수집·주의보에서는 제외하되 키워드 검색은 유지
MOA_KEYWORDS = tuple(
    dict.fromkeys(
        [k for k in PHISHING_SEED_QUERIES if k != "피싱"] + ["전세사기"]
    )
)

_ALERT_KEYWORD_TO_MOA = {
    "편취": "보이스피싱",
    "사칭": "기관사칭",
    "악성링크": "스미싱",
    "악성앱": "스미싱",
    "원격제어": "보이스피싱",
    "팀뷰어": "보이스피싱",
    "계좌이체": "보이스피싱",
    "송금": "보이스피싱",
    "금전요구": "보이스피싱",
    "상품권": "메신저피싱",
    "리딩방": "리딩방",
    "가상자산": "고수익 투자",
    "협박": "몸캠피싱",
    "유포": "몸캠피싱",
    "OTP": "스미싱",
    "인증번호": "스미싱",
    "휴대폰 렌탈 사기": "신종 사기",
    "렌탈사기": "신종 사기",
    "렌터카사기": "신종 사기",
    "검찰·경찰 등 수사기관 사칭": "기관사칭",
    "금융감독원·은행 등 금융기관 사칭": "금융기관 사칭",
    "가족·지인 사칭 급전 요구": "지인사칭",
    "악성 문자·링크 클릭 유도": "스미싱",
    "QR코드 스캔 유도": "큐싱",
    "메신저(카톡 등)로 금전·상품권 요구": "메신저피싱",
    "원격제어 앱 설치 요구": "보이스피싱",
    "고수익 투자·리딩방 유인": "리딩방",
    "영상·딥페이크 협박·사칭": "딥페이크",
    "지원금·환급 미끼": "정부지원금 사기",
    "렌탈·렌터카·카셰어링 명의 대여 후 미반납·추가금 요구": "신종 사기",
    "신종·변형 수법 언급": "신종 사기",
}


def map_alert_keyword_to_moa(keyword: str) -> str | None:
    """주의보 키워드를 Da Moa 검색어로 매핑."""
    if keyword in MOA_KEYWORDS:
        return keyword
    mapped = _ALERT_KEYWORD_TO_MOA.get(keyword)
    if mapped and mapped in MOA_KEYWORDS:
        return mapped
    for moa_kw in sorted(MOA_KEYWORDS, key=len, reverse=True):
        if moa_kw in keyword or keyword in moa_kw:
            return moa_kw
    return None


def resolve_moa_search_keyword(alert_keyword: str) -> str:
    """주의보 키워드 → Da Moa API 검색어."""
    return map_alert_keyword_to_moa(alert_keyword) or alert_keyword


def scroll_to_dom_id(
    element_id: str,
    *,
    block: str = "start",
    delay_ms: int = 80,
    retries: tuple[int, ...] = (0, 200),
    fallback_selector: str | None = None,
    offset_px: int = 80,
    grace_ms: int = 200,
) -> None:
    """리런 후 스크롤 위치 복원.

    목표 위치에 한 번 도착하면 재시도를 중단하고,
    사용자가 스크롤하면 즉시 자동 스크롤을 멈춥니다.
    """
    delays = [delay_ms + r for r in retries]
    nonce = f"{datetime.now().timestamp()}-{id(element_id)}"
    components.html(
        "<script>"
        "(function(){"
        f"const _nonce={json.dumps(nonce)};"
        f"const id={json.dumps(element_id)};"
        f"const delays={json.dumps(delays)};"
        f"const fallback={json.dumps(fallback_selector)};"
        f"const offset={int(offset_px)};"
        f"const graceUntil=Date.now()+{int(grace_ms)};"
        "const d=window.parent.document;"
        "const w=window.parent;"
        "let cancelled=false;"
        "let landed=false;"
        "const timers=[];"
        "function stopAll(){"
        "if(cancelled) return;"
        "cancelled=true;"
        "timers.forEach(function(t){clearTimeout(t);});"
        "timers.length=0;"
        "['wheel','touchmove','touchstart'].forEach(function(ev){"
        "w.removeEventListener(ev, onUser, true);"
        "d.removeEventListener(ev, onUser, true);"
        "});"
        "}"
        "function onUser(){"
        "if(cancelled) return;"
        "if(!landed && Date.now()<graceUntil) return;"
        "stopAll();"
        "}"
        "['wheel','touchmove','touchstart'].forEach(function(ev){"
        "w.addEventListener(ev, onUser, {capture:true, passive:true});"
        "d.addEventListener(ev, onUser, {capture:true, passive:true});"
        "});"
        "function findEl(){"
        "return d.getElementById(id)"
        "|| (fallback ? d.querySelector(fallback) : null);"
        "}"
        "function isScrollable(node){"
        "if(!node) return false;"
        "try{"
        "const s=w.getComputedStyle(node);"
        "const oy=s.overflowY||'';"
        "return (oy==='auto'||oy==='scroll'||oy==='overlay')"
        "&& node.scrollHeight>node.clientHeight+4;"
        "}catch(e){return false;}"
        "}"
        "function candidates(el){"
        "const list=[];"
        "let n=el?el.parentElement:null;"
        "while(n && n!==d.documentElement){"
        "if(isScrollable(n)) list.push(n);"
        "n=n.parentElement;"
        "}"
        "["
        "d.querySelector('[data-testid=\"stMain\"]'),"
        "d.querySelector('section.main'),"
        "d.querySelector('[data-testid=\"stAppViewContainer\"]'),"
        "d.querySelector('.main'),"
        "d.querySelector('.stApp'),"
        "d.scrollingElement,"
        "d.documentElement,"
        "d.body"
        "].forEach(function(m){ if(m && list.indexOf(m)<0) list.push(m); });"
        "return list;"
        "}"
        "function nearTarget(el){"
        "try{"
        "const top=el.getBoundingClientRect().top;"
        "return Math.abs(top-offset)<56;"
        "}catch(e){return false;}"
        "}"
        "function shouldAssist(el){"
        "try{"
        "const top=el.getBoundingClientRect().top;"
        "const vh=w.innerHeight||600;"
        "if(top < -80) return false;"
        "if(Math.abs(top-offset)<56) return false;"
        "if(top>=0 && top < vh*0.55) return false;"
        "return true;"
        "}catch(e){return true;}"
        "}"
        "function apply(el){"
        "try{el.scrollIntoView({behavior:'auto',block:'start'});}catch(e){"
        "try{el.scrollIntoView(true);}catch(e2){}"
        "}"
        "candidates(el).forEach(function(main){"
        "try{"
        "const top=el.getBoundingClientRect().top"
        "-main.getBoundingClientRect().top+(main.scrollTop||0)-offset;"
        "main.scrollTop=Math.max(0,top);"
        "if(typeof main.scrollTo==='function'){"
        "main.scrollTo(0,Math.max(0,top));"
        "}"
        "}catch(e){}"
        "});"
        "try{"
        "const y=el.getBoundingClientRect().top+(w.scrollY||0)-offset;"
        "w.scrollTo(0,Math.max(0,y));"
        "if(d.documentElement) d.documentElement.scrollTop=Math.max(0,y);"
        "if(d.body) d.body.scrollTop=Math.max(0,y);"
        "}catch(e){}"
        "}"
        "function go(){"
        "if(cancelled) return;"
        "const el=findEl();"
        "if(!el) return;"
        "if(!shouldAssist(el)){"
        "landed=true;"
        "stopAll();"
        "return;"
        "}"
        "apply(el);"
        "if(!shouldAssist(el) || nearTarget(el)){"
        "landed=true;"
        "stopAll();"
        "}"
        "}"
        "delays.forEach(function(t){timers.push(setTimeout(go, t));});"
        "timers.push(setTimeout(stopAll,"
        "Math.max.apply(null, delays.concat([0])) + 80));"
        "})();"
        "</script>",
        height=1,
    )


# 모바일 레이아웃 반영을 위해 약간 여유 있게 재시도
_SECTION_SCROLL_RETRIES = (0, 80, 220, 480)
_MORE_SCROLL_RETRIES = (0, 60, 160)


def scroll_to_alert_screen() -> None:
    """주의보(키워드·예방 포인트) 화면으로 스크롤."""
    scroll_to_dom_id(
        "alert-stay-anchor",
        delay_ms=0,
        retries=_SECTION_SCROLL_RETRIES,
        fallback_selector=".phishing-alert-hero",
        offset_px=72,
    )


def scroll_to_method_screen() -> None:
    """피싱 수법 Da Moa 화면으로 스크롤."""
    scroll_to_dom_id(
        "method-stay-anchor",
        delay_ms=0,
        retries=_SECTION_SCROLL_RETRIES,
        fallback_selector=".phishing-backseo-hero",
        offset_px=72,
    )


def scroll_to_moa_screen() -> None:
    """키워드(최신 피싱 기사 Da Moa) 화면으로 스크롤."""
    scroll_to_dom_id(
        "moa-stay-anchor",
        delay_ms=0,
        retries=_SECTION_SCROLL_RETRIES,
        fallback_selector=".phishing-moa-hero",
        offset_px=72,
    )


def close_alert_inline_list() -> None:
    """주의보 기사 목록만 닫고 주의보 화면으로 복귀."""
    clear_moa_keyword_selection()
    st.session_state.scroll_stay_alert_close = True


def close_method_article_list() -> None:
    """수법 기사 목록 닫고 피싱 수법 화면으로 복귀."""
    st.session_state.method_list_closed = True
    st.session_state.pop("method_list_close_cb", None)
    st.session_state.scroll_stay_method_close = True


def close_moa_keyword_list() -> None:
    """키워드 기사 목록 닫고 키워드 Da Moa 화면으로 복귀."""
    clear_moa_keyword_selection()
    st.session_state.scroll_stay_moa_close = True


def clear_moa_keyword_selection() -> None:
    """키워드 선택(X)·직접 검색(X)·닫기 시 주의보·검색 상태까지 함께 비웁니다."""
    prev_kw = st.session_state.get("moa_active_keyword")
    st.session_state.pop("moa_active_keyword", None)
    st.session_state.pop("moa_search_source", None)
    st.session_state.pop("moa_from_alert_nav", None)
    st.session_state.pop("moa_alert_display_kw", None)
    st.session_state.pop("moa_alert_bound_to_picker", None)
    st.session_state.pop("alert_inline_close_cb", None)
    st.session_state.pop("moa_list_close_cb", None)
    st.session_state.pop("moa_crime_only", None)
    if prev_kw:
        discard_widget_key(_moa_more_button_key(str(prev_kw)))
    discard_widget_key(st.session_state.pop("moa_more_key_last", None))
    # selectbox/입력 위젯이 이미 만들어진 뒤에는 key를 직접 수정할 수 없음 → 다음 실행에서 비움
    st.session_state.moa_pending_clear_picker = True
    st.session_state.moa_pending_clear_custom_input = True
    st.session_state.moa_pending_clear_custom_chip = True
    st.session_state.moa_last_picked = None
    st.session_state.moa_display_count = 5
    st.session_state.pop("scroll_to_moa_articles", None)
    # URL에 ?alert_moa= 가 남아 다시 켜지지 않도록 nonce 갱신
    st.session_state.moa_alert_link_nonce = (
        int(st.session_state.get("moa_alert_link_nonce") or 1) + 1
    )
    if "alert_moa" in st.query_params:
        try:
            del st.query_params["alert_moa"]
        except Exception:
            pass
    if "n" in st.query_params:
        try:
            del st.query_params["n"]
        except Exception:
            pass


def on_moa_custom_chip_change() -> None:
    """직접 검색어 selectbox의 X — 검색어·기사 목록 삭제."""
    if st.session_state.get("moa_custom_chip") is None:
        clear_moa_keyword_selection()
        st.session_state.scroll_stay_moa_close = True


def on_moa_crime_only_change() -> None:
    """범죄기사 필터 토글 시 목록을 처음부터 다시 보여 줌."""
    st.session_state.moa_display_count = 5


def on_moa_keyword_picker_change() -> None:
    """selectbox 변경/X 해제."""
    picked = st.session_state.get("moa_keyword_picker")
    st.session_state.moa_display_count = 5
    st.session_state.pop("moa_crime_only", None)
    if picked is None:
        if st.session_state.get("moa_search_source") == "custom":
            # 직접 검색 중 picker X는 무시 (직접 검색어 X로 지움)
            st.session_state.moa_last_picked = None
            return
        # 주의보 열람 중 picker는 비워 두므로, 더보기 등으로 None이 되어도 목록은 유지
        if st.session_state.get("moa_search_source") == "alert":
            st.session_state.moa_last_picked = None
            return
        # X → 키워드 검색 상태 해제
        clear_moa_keyword_selection()
        st.session_state.scroll_stay_moa_close = True
        return
    prev_kw = st.session_state.get("moa_active_keyword")
    if prev_kw and prev_kw != picked:
        discard_widget_key(_moa_more_button_key(str(prev_kw)))
    st.session_state.moa_last_picked = picked
    st.session_state.moa_active_keyword = picked
    st.session_state.moa_search_source = "picker"
    st.session_state.pop("moa_from_alert_nav", None)
    st.session_state.pop("moa_alert_display_kw", None)
    st.session_state.pop("moa_alert_bound_to_picker", None)
    st.session_state.moa_pending_clear_custom_input = True
    st.session_state.moa_pending_clear_custom_chip = True
    st.session_state.scroll_to_moa_articles = True


def trigger_moa_from_alert(alert_keyword: str) -> None:
    """주의보 키워드 클릭 → 예방 포인트 아래 집계 기사 표시."""
    st.session_state.moa_active_keyword = alert_keyword
    st.session_state.moa_search_source = "alert"
    st.session_state.moa_alert_display_kw = alert_keyword
    # 선택창에 키워드를 넣지 않음 — 모바일에서 X가 안 지워지는 잔상 방지
    st.session_state.moa_pending_clear_picker = True
    st.session_state.moa_last_picked = None
    st.session_state.moa_alert_bound_to_picker = False
    st.session_state.moa_display_count = 5
    st.session_state.moa_from_alert_nav = True
    # query_params 정리 리런 1회까지 스크롤 유지
    st.session_state.scroll_to_alert_news = 2
    st.session_state.moa_pending_clear_custom_input = True
    st.session_state.moa_pending_clear_custom_chip = True


def _moa_more_button_key(keyword: str) -> str:
    return "moa_more_" + re.sub(r"\W+", "_", keyword or "kw")


def discard_widget_key(*keys: str | None) -> None:
    """렌더하지 않을 위젯 key를 미리 제거 (Streamlit orphan key 오류 방지)."""
    for key in keys:
        if key:
            st.session_state.pop(key, None)


def render_more_with_close(
    *,
    more_label: str | None,
    more_key: str | None,
    close_key: str,
    done_caption: str | None = None,
) -> str | None:
    """더보기 옆에 닫기(체크박스) — 'more' | 'close' | None.

    더보기 클릭 시 닫기 체크가 남아 있어도 more를 우선한다.
    """
    # 직전 더보기 직후 닫기 체크 잔상 제거 (위젯 생성 전)
    if st.session_state.pop(f"_clear_{close_key}", False):
        st.session_state.pop(close_key, None)

    left, right = st.columns([4, 1])
    more_clicked = False
    with left:
        if more_label and more_key:
            more_clicked = st.button(
                more_label, key=more_key, use_container_width=True
            )
        elif done_caption:
            st.caption(done_caption)
    with right:
        close_checked = st.checkbox("닫기", key=close_key)

    if more_clicked:
        return "more"
    if close_checked:
        return "close"
    return None


def render_alert_inline_articles(articles: list[dict], keyword: str) -> None:
    """예방 포인트 바로 아래 — 주의 키워드 기사 목록."""
    st.markdown(
        '<div id="alert-news-section" style="height:1px;margin:0;padding:0;"></div>'
        f'<p class="phishing-moa-card-label">'
        f"🚨 주의 키워드 「{html.escape(keyword)}」 "
        f"기사 목록 {len(articles)}건</p>",
        unsafe_allow_html=True,
    )

    if not articles:
        st.info(f"「{keyword}」 주의 키워드 기사 목록에 포함된 기사가 없습니다.")
        if st.session_state.pop("_clear_alert_inline_close_cb", False):
            st.session_state.pop("alert_inline_close_cb", None)
        if st.checkbox("닫기", key="alert_inline_close_cb"):
            close_alert_inline_list()
            st.rerun()
        return

    render_naver_api_attribution()

    focus_idx = st.session_state.pop("scroll_to_alert_article", None)
    visible = articles[: st.session_state.moa_display_count]
    for idx, news in enumerate(visible, 1):
        if focus_idx is not None and idx == focus_idx:
            st.markdown('<div id="alert-article-focus"></div>', unsafe_allow_html=True)
        kw_label = (
            " · ".join(news["keywords"])
            if news.get("keywords")
            else (news.get("analysis") or {}).get("primary", keyword)
        )
        with st.container(border=True):
            st.markdown(f"**{idx}. [{news['title']}]({news['link']})**")
            st.caption(
                f"📢 {news.get('press', '')} | 🗓️ {news.get('date', '')} | 🏷️ {kw_label}"
            )
            if news.get("description"):
                snippet = news["description"]
                st.write(snippet[:160] + ("…" if len(snippet) > 160 else ""))

    if focus_idx is not None:
        scroll_to_dom_id(
            "alert-article-focus",
            delay_ms=0,
            retries=_MORE_SCROLL_RETRIES,
            offset_px=32,
        )

    remaining = len(articles) - st.session_state.moa_display_count
    if remaining > 0:
        add_count = min(10, remaining)
        action = render_more_with_close(
            more_label=f"🔽 「{keyword}」 더보기 ({add_count}개 추가)",
            more_key="alert_inline_more_" + re.sub(r"\W+", "_", keyword),
            close_key="alert_inline_close_cb",
        )
    else:
        action = render_more_with_close(
            more_label=None,
            more_key=None,
            close_key="alert_inline_close_cb",
            done_caption=f"「{keyword}」 기사 {len(articles)}건을 모두 표시했습니다.",
        )

    if action == "more":
        # 클릭 시점(=직전까지 보던 다음 기사)에 머물도록
        prev_count = st.session_state.moa_display_count
        st.session_state.moa_display_count = prev_count + 10
        st.session_state.scroll_to_alert_article = prev_count + 1
        st.session_state.moa_search_source = "alert"
        if st.session_state.get("moa_alert_display_kw"):
            st.session_state.moa_active_keyword = st.session_state.moa_alert_display_kw
        st.session_state["_clear_alert_inline_close_cb"] = True
        st.rerun()
    elif action == "close":
        close_alert_inline_list()
        st.rerun()


# 파트2 스크랩용 추가 금융 사기 검색어
FINANCIAL_FRAUD_EXTRA_QUERIES = (
    "대출사기",
    "리딩방 사기",
    "가상자산 사기",
    "코인 사기",
    "보험금 사기",
    "대포통장",
    "카드깡",
    "명의도용 사기",
    "환전 사기",
    "송금 사기",
)
ALL_NEWS_SCRAP_QUERIES = tuple(
    dict.fromkeys(PHISHING_SEED_QUERIES + FINANCIAL_FRAUD_EXTRA_QUERIES)
)
PHISHING_RELATED_TERMS = set(PHISHING_SEED_QUERIES) | set(PHISHING_KEYWORDS) | {
    "피싱",
    "금융사기",
    "전화금융사기",
    "카셰어링",
}
FINANCIAL_FRAUD_TERMS = PHISHING_RELATED_TERMS | {
    "대출사기",
    "리딩방",
    "가상자산",
    "가상화폐",
    "코인",
    "코인사기",
    "보험금",
    "대포통장",
    "카드깡",
    "명의도용",
    "환전",
    "금융",
    "계좌",
    "통장",
    "대출",
    "투자",
    "리딩",
    "송금",
    "이체",
    "편취",
    "사칭",
    "사기",
    "기승",
    "신종",
    "신종수법",
    "급증",
}
EDITORIAL_MARKERS = (
    "[기고]",
    "[칼럼]",
    "[사설]",
    "[논설]",
    "[오피니언]",
    "[시론]",
    "[기고문]",
    "[데스크]",
    "[독자투고]",
    "[독자]",
    "칼럼]",
    "기고]",
    "사설]",
    "논설]",
    "독자투고]",
    "독자]",
    "기고문",
    "칼럼니스트",
    "오피니언",
    "데스크 칼럼",
    "Editorial",
    "기자수첩",
    "시론·",
    "사설·",
    "독자투고",
    "독자 투고",
    "독자기고",
    "독자 기고",
    "독자의견",
    "독자 의견",
    "독자제보",
)
SEED_SEARCH_LABEL = "피싱·보이스피싱·금융사기 등"
# 키워드 순위 집계에서 제외할 포괄 검색어
GENERIC_SEED_EXCLUDE = {
    "피싱",
    "보이스피싱",
    "보이스",
    "금융사기",
    "금융",
    "은행",
    "사기",
}
PRIMARY_RESEARCH_SEEDS = ("피싱", "보이스피싱", "금융사기")
# 3단계 재검색 — 키워드 수·쿼리 수 (API 호출 절감)
RESEARCH_KEYWORD_TOP_N = 10
# 1단계 시드 검색 — 네이버 display 최대 100
SEED_QUERY_DISPLAY = 100
INVESTIGATION_ONLY_MARKERS = (
    "검거",
    "송치",
    "구속",
    "기소",
    "체포",
    "수사",
    "단속",
    "적발",
    "구형",
    "징역",
)
CRIME_BEHAVIOR_MARKERS = (
    "사칭",
    "편취",
    "유인",
    "갈취",
    "미끼",
    "유도",
    "이체",
    "송금",
    "협박",
    "유포",
    "악성",
    "원격",
    "링크",
    "계좌",
    "명의",
    "대포",
    "상품권",
    "OTP",
    "인증번호",
    "리딩",
    "가상자산",
    "딥페이크",
    "가짜",
    "설치",
    "QR",
)

_INVESTIGATION_EXCLUDED_LOWER = {k.lower() for k in INVESTIGATION_META_EXCLUDE_KEYWORDS}
_DERIVED_ALLOWLIST_LOWER = {k.lower() for k in DERIVED_KEYWORD_ALLOWLIST}
_GENERIC_DERIVED_EXCLUDED_LOWER = {k.lower() for k in GENERIC_DERIVED_KEYWORD_EXCLUDE}


def keyword_action_priority(keyword: str) -> int:
    """재검색 키워드 우선순위. 수사·검거 계열은 -1(제외)."""
    if keyword.lower() in _INVESTIGATION_EXCLUDED_LOWER:
        return -1
    if keyword in HIGH_PRIORITY_ACTION_KEYWORDS:
        return 3
    if keyword in MEDIUM_PRIORITY_ACTION_KEYWORDS:
        return 2
    if keyword.lower() in _DERIVED_ALLOWLIST_LOWER:
        return 1
    return -1


def strip_investigation_terms(text: str) -> str:
    """본문에서 수사·검거 관련 표현을 제거해 행위 키워드 집계를 돕습니다."""
    work = text
    for term in sorted(INVESTIGATION_META_EXCLUDE_KEYWORDS, key=len, reverse=True):
        work = work.replace(term, " ")
    return work


def rank_derived_keywords(counter: Counter, top_n: int = 10) -> list[tuple[str, int]]:
    """빈도 + 행위 우선순위로 재검색 키워드를 정렬합니다."""
    ranked: list[tuple[str, int, int]] = []
    for keyword, count in counter.items():
        priority = keyword_action_priority(keyword)
        if priority < 0:
            continue
        if keyword.lower() not in _DERIVED_ALLOWLIST_LOWER:
            continue
        if keyword.lower() in _GENERIC_DERIVED_EXCLUDED_LOWER:
            continue
        ranked.append((keyword, count, priority))

    ranked.sort(key=lambda item: (item[2], item[1]), reverse=True)
    return [(keyword, count) for keyword, count, _ in ranked[:top_n]]


def filter_keywords_for_research(keyword_rank: list[tuple[str, int]]) -> list[str]:
    """재검색에 사용할 행위 위주 키워드만 추출합니다."""
    selected: list[str] = []
    for keyword, _count in keyword_rank:
        if keyword_action_priority(keyword) < 1:
            continue
        if keyword.lower() in _INVESTIGATION_EXCLUDED_LOWER:
            continue
        selected.append(keyword)
        if len(selected) >= RESEARCH_KEYWORD_TOP_N:
            break
    return selected


def is_phishing_related_article(
    title: str, description: str, keywords: list[str]
) -> bool:
    combined = f"{title} {description}"
    if keywords:
        return True
    return any(term in combined for term in PHISHING_RELATED_TERMS)


def is_financial_fraud_article(
    title: str, description: str, keywords: list[str]
) -> bool:
    """다양한 금융·피싱 사기 관련 기사 여부."""
    combined = f"{title} {description}"
    if keywords:
        return True
    return any(term in combined for term in FINANCIAL_FRAUD_TERMS)


def is_editorial_or_opinion_article(
    title: str, description: str, link: str = ""
) -> bool:
    """기고·칼럼·사설·논설 등 기고문 성격 기사."""
    text = f"{title} {description} {link}"
    if any(marker in text for marker in EDITORIAL_MARKERS):
        return True
    if re.search(
        r"\[(기고|칼럼|사설|논설|오피니언|시론|기고문|데스크|독자투고|독자)\]", title
    ):
        return True
    link_lower = link.lower()
    if any(
        part in link_lower
        for part in ("/opinion/", "/column/", "/editorial/", "section=opinion")
    ):
        return True
    return False


def is_crime_action_article(
    title: str, description: str, keywords: list[str], tactics: list[str]
) -> bool:
    """피싱·사기 기사 중 범죄 행위·수단이 드러나는 기사만 통과."""
    combined = f"{title} {description}"
    if not is_phishing_related_article(title, description, keywords):
        return False

    action_keywords = [
        kw
        for kw in keywords
        if keyword_action_priority(kw) >= 1 or kw in PHISHING_KEYWORDS
    ]
    behavior_hits = sum(1 for word in CRIME_BEHAVIOR_MARKERS if word in combined)
    has_action_phrase = any(
        phrase in combined
        for phrase in sorted(DERIVED_KEYWORD_ALLOWLIST, key=len, reverse=True)
        if phrase.lower() not in _INVESTIGATION_EXCLUDED_LOWER
    )
    investigation_hits = sum(
        1 for word in INVESTIGATION_ONLY_MARKERS if word in combined
    )

    has_crime_behavior = bool(tactics) or bool(action_keywords) or behavior_hits >= 1 or has_action_phrase
    if not has_crime_behavior:
        return False
    if investigation_hits >= 2 and not tactics and not action_keywords and behavior_hits == 0:
        return False
    return is_actual_case_article(title, description, keywords, tactics)


def build_research_queries(action_keyword: str) -> list[str]:
    """범죄 행위 키워드로 피싱·보이스피싱·금융사기 시드 3종 재검색."""
    queries = [f"{seed} {action_keyword}" for seed in PRIMARY_RESEARCH_SEEDS]
    if action_keyword not in queries:
        queries.append(action_keyword)
    return list(dict.fromkeys(queries))


def scrape_keyword_frequency(
    news_items: list[dict],
    top_n: int = 30,
    exclude_keywords: set[str] | None = None,
    crime_only: bool = True,
) -> list[tuple[str, int]]:
    """뉴스 제목·요약에서 키워드를 추출해 빈도순으로 반환합니다.

    crime_only=True 이면 범죄 행위·수단 관련 키워드만 집계합니다.
    """
    counter: Counter = Counter()
    excluded = {e.lower() for e in (exclude_keywords or set())}
    excluded.update(k.lower() for k in NON_CRIME_EXCLUDE_KEYWORDS)
    excluded.update(k.lower() for k in INVESTIGATION_META_EXCLUDE_KEYWORDS)

    allowlist = {
        k.lower(): k
        for k in DERIVED_KEYWORD_ALLOWLIST
        if k.lower() not in excluded and k.lower() not in _GENERIC_DERIVED_EXCLUDED_LOWER
    }
    # 긴 구문부터 매칭
    phrases = sorted(allowlist.values(), key=len, reverse=True)

    for news in news_items:
        text = f"{news.get('title', '')} {news.get('description', '')}"
        work = strip_investigation_terms(text)

        # 시드·포괄 표현 제거 (복합 수법명은 allowlist에서 긴 구문 우선 매칭)
        for bad in ("보이스피싱", "보이스 피싱", "보이스"):
            work = work.replace(bad, " ")
        work = re.sub(r"(?<![가-힣])피싱(?![가-힣])", " ", work)
        work = re.sub(r"(?<![가-힣])금융사기(?![가-힣])", " ", work)

        for phrase in phrases:
            key = phrase.lower()
            if key in excluded:
                continue
            if phrase.isascii():
                hits = len(re.findall(re.escape(phrase), work, flags=re.IGNORECASE))
            else:
                hits = work.count(phrase)
            if hits:
                # 기사 1건당 키워드 1회만 집계 (동일 기사 내 중복 언급은 무시)
                counter[allowlist.get(key, phrase)] += 1
                if phrase.isascii():
                    work = re.sub(re.escape(phrase), " ", work, flags=re.IGNORECASE)
                else:
                    work = work.replace(phrase, " ")

        if not crime_only:
            for token in re.findall(r"[가-힣]{2,}", work):
                if token in KEYWORD_STOPWORDS or token.lower() in excluded:
                    continue
                if token.endswith(("습니다", "했습니다", "했습니다만")):
                    continue
                counter[token] += 1

    for key in list(counter.keys()):
        if key.lower() in excluded:
            del counter[key]
        elif crime_only and key.lower() not in allowlist:
            del counter[key]

    return rank_derived_keywords(counter, top_n)


def article_counts_toward_alert_keyword(news: dict, keyword: str) -> bool:
    """주의보 scrape_keyword_frequency와 동일 규칙으로 해당 키워드가 집계되는지."""
    target = (keyword or "").strip()
    if not target:
        return False

    excluded = {k.lower() for k in NON_CRIME_EXCLUDE_KEYWORDS}
    excluded.update(k.lower() for k in INVESTIGATION_META_EXCLUDE_KEYWORDS)
    allowlist = {
        k.lower(): k
        for k in DERIVED_KEYWORD_ALLOWLIST
        if k.lower() not in excluded and k.lower() not in _GENERIC_DERIVED_EXCLUDED_LOWER
    }
    phrases = sorted(allowlist.values(), key=len, reverse=True)

    text = f"{news.get('title', '')} {news.get('description', '')}"
    work = strip_investigation_terms(text)
    for bad in ("보이스피싱", "보이스 피싱", "보이스"):
        work = work.replace(bad, " ")
    work = re.sub(r"(?<![가-힣])피싱(?![가-힣])", " ", work)
    work = re.sub(r"(?<![가-힣])금융사기(?![가-힣])", " ", work)

    target_lower = target.lower()
    for phrase in phrases:
        key = phrase.lower()
        if phrase.isascii():
            hits = len(re.findall(re.escape(phrase), work, flags=re.IGNORECASE))
        else:
            hits = work.count(phrase)
        if not hits:
            continue
        matched = allowlist.get(key, phrase)
        if matched == target or matched.lower() == target_lower:
            return True
        # 더 긴 구문이 먼저 먹으면 해당 구간 제거 후 계속 (집계와 동일)
        if phrase.isascii():
            work = re.sub(re.escape(phrase), " ", work, flags=re.IGNORECASE)
        else:
            work = work.replace(phrase, " ")
    return False


# 주의 키워드 목록 — 광고·홍보성 문구 (뒤로 보냄)
ALERT_LIST_AD_PROMO_WORDS = (
    "광고",
    "유료광고",
    "광고문의",
    "협찬",
    "스폰서",
    "프로모션",
    "이벤트",
    "할인",
    "특가",
    "체험단",
    "원고료",
    "제공=",
    "제공 =",
    "홍보",
    "캠페인",
    "설명회",
    "간담회",
    "예방교육",
    "예방 교육",
)


def alert_article_priority_score(article: dict) -> int:
    """주의 키워드 목록 정렬 — 수법·행위·피해 사례를 광고·홍보보다 앞에."""
    title = (article.get("title") or "").strip()
    description = article.get("description") or ""
    link = article.get("link") or ""
    combined = f"{title} {description}"
    score = 0

    # 피해·수법·수사·행위 신호 (높을수록 앞)
    if has_confirmed_victim_evidence(combined):
        score += 45
    if has_crime_case_narrative(combined):
        score += 35
    if is_moa_crime_only_article(title, description):
        score += 30
    if any(w in combined for w in ("수법", "범행", "사칭", "편취", "갈취", "탈취")):
        score += 18
    if any(
        w in combined
        for w in ("피해자", "피해액", "피해금", "억원", "송금", "이체", "인출")
    ):
        score += 14
    score += min(count_substance_hits(combined), 8) * 3
    if qualifies_as_case_or_surge_report(combined):
        score += 10

    analysis = article.get("analysis") or {}
    tactics = analysis.get("tactics") or article.get("tactics") or []
    if tactics:
        score += min(len(tactics), 5) * 5
    keywords = article.get("keywords") or analysis.get("keywords") or []
    if keywords:
        score += min(len(keywords), 4) * 2

    # 광고·홍보·예방 안내성 (낮을수록 뒤)
    if any(w in combined for w in ALERT_LIST_AD_PROMO_WORDS):
        score -= 55
    if has_promo_activity_context(combined) or is_promo_title_article(
        title, description
    ):
        score -= 40
    if is_prevention_advice_article(title, description):
        score -= 35
    if is_police_station_promo_article(title, description):
        score -= 30
    if is_alert_promo_excluded_article(title, description, link):
        score -= 25

    return score


def filter_articles_by_alert_keyword(
    articles: list[dict], keyword: str
) -> list[dict]:
    """주의보 N회 집계에 실제로 포함된 기사만 반환.

    수법·행위·피해 사례를 광고·홍보성 기사보다 앞에 둡니다.
    """
    kw = (keyword or "").strip()
    if not kw:
        return []
    matched = [
        article
        for article in articles
        if article_counts_toward_alert_keyword(article, kw)
    ]
    matched.sort(
        key=lambda x: (
            alert_article_priority_score(x),
            x.get("datetime") or datetime.min,
        ),
        reverse=True,
    )
    return dedupe_articles_by_title(matched)


def _modus_cue_in_text(text: str, cue: str) -> bool:
    if not cue:
        return False
    if cue.isascii():
        return cue.lower() in text.lower()
    return cue in text


def _modus_group_hit(text: str, group: tuple[str, ...] | list[str]) -> bool:
    return any(_modus_cue_in_text(text, cue) for cue in group)


def _modus_rule_matches(text: str, rule: dict) -> tuple[bool, int]:
    """규칙 매칭 여부와 강도(2=강함, 1=약함)를 반환합니다."""
    strength = 0
    for cue in rule.get("strong") or ():
        if _modus_cue_in_text(text, cue):
            strength = 2
            break
    for combo in rule.get("combos") or ():
        if len(combo) < 2:
            continue
        group_a, group_b = combo[0], combo[1]
        if _modus_group_hit(text, group_a) and _modus_group_hit(text, group_b):
            strength = max(strength, 2)
    return strength > 0, strength


def _modus_type_compatible(primary: str | None, rule: dict) -> bool:
    allowed = rule.get("types") or set()
    if not allowed:
        return True
    if not primary or primary in ("피싱(유형 미상)", "피싱"):
        return True
    return primary in allowed


def detect_modus_operandi_detailed(
    text: str, primary: str | None = None
) -> list[tuple[str, int]]:
    """(수법 라벨, 강도) 목록. 강도 2=강한 단서/조합, 1=보조."""
    hits: list[tuple[str, int]] = []
    for rule in MODUS_RULES:
        matched, strength = _modus_rule_matches(text, rule)
        if not matched:
            continue
        if not _modus_type_compatible(primary, rule):
            continue
        hits.append((rule["label"], strength))
    hits.sort(key=lambda item: (-item[1], item[0]))
    return hits


def detect_modus_operandi(text: str, primary: str | None = None) -> list[str]:
    """호환용 — 수법 라벨만 반환."""
    return [label for label, _strength in detect_modus_operandi_detailed(text, primary)]


def analyze_crime_method(title: str, description: str, keywords: list[str]) -> dict:
    """기사 제목·요약에서 수법 유형과 구체적 범행 방식을 추출합니다."""
    combined = f"{title} {description}"
    primary = keywords[0] if keywords else "피싱(유형 미상)"
    profile = METHOD_PROFILES.get(
        primary,
        {
            "how": "기사에 나타난 피싱·사기 정황을 바탕으로 금전·정보 편취를 시도한 사례로 보입니다.",
            "watch": "금전·개인정보 요구, 링크 클릭 유도가 있으면 일단 중단하고 공식 경로로 확인하세요.",
        },
    )

    title_hits = detect_modus_operandi_detailed(title, primary)
    body_hits = detect_modus_operandi_detailed(combined, primary)
    # 제목 단서 우선, 라벨 기준 중복 제거
    merged: dict[str, int] = {}
    for label, strength in title_hits:
        merged[label] = max(merged.get(label, 0), strength + 1)  # 제목 가중
    for label, strength in body_hits:
        merged[label] = max(merged.get(label, 0), strength)
    ranked = sorted(merged.items(), key=lambda item: (-item[1], item[0]))
    tactics = [label for label, _ in ranked]

    title_bonus = bool(title_hits)
    strong_count = sum(1 for _label, strength in ranked if strength >= 2)
    if (len(tactics) >= 2 and strong_count >= 1) or (title_bonus and strong_count >= 1):
        confidence = "high"
    elif tactics:
        confidence = "medium"
    else:
        confidence = "low"

    if confidence == "high":
        how_detail = (
            f"이 기사에서는 **{primary}** 유형으로 보이며, "
            f"구체적으로 **{' / '.join(tactics)}** 방식이 확인됩니다. "
            f"{profile['how']}"
        )
    elif confidence == "medium":
        how_detail = (
            f"이 기사는 **{primary}** 관련으로 보이며, "
            f"요약상 **{' / '.join(tactics)}** 방식으로 **추정**됩니다. "
            f"{profile['how']}"
        )
    else:
        how_detail = (
            f"이 기사는 **{primary}** 관련 보도로 **추정**됩니다. "
            f"구체 수법 단서가 부족해 유형 기본 설명을 안내합니다. {profile['how']}"
        )

    return {
        "primary": primary,
        "keywords": keywords,
        "tactics": tactics,
        "confidence": confidence,
        "how_detail": how_detail,
        "watch": profile["watch"],
        "snippet": description[:180] + ("…" if len(description) > 180 else ""),
    }


@st.cache_data(ttl=NAVER_API_CACHE_TTL, show_spinner=False)
def fetch_moa_keyword_news(
    client_id: str, client_secret: str, keyword: str, _cache_ver: int = 7
) -> tuple[list[dict], str | None]:
    """Da Moa — 키워드 1개당 네이버 API 1회 호출 (최대 100건, 키워드 연관 기사 전체)."""
    try:
        res = requests.get(
            NAVER_NEWS_SEARCH_URL,
            headers=naver_news_search_headers(client_id, client_secret),
            params=naver_news_search_params(keyword, display=100),
            timeout=10,
        )
        res.raise_for_status()
        raw_items = res.json().get("items", [])
    except requests.HTTPError as e:
        return [], format_naver_search_error(keyword, e)
    except requests.RequestException as e:
        return [], f"「{keyword}」 네트워크 오류: {e}"

    past_month = datetime.now() - timedelta(days=30)
    articles: list[dict] = []
    seen: set[str] = set()
    for item in raw_items:
        try:
            link = item.get("link") or item.get("originallink") or ""
            if not link or link in seen:
                continue

            pub_date = parsedate_to_datetime(item["pubDate"]).replace(tzinfo=None)
            if pub_date < past_month:
                continue

            title = clean_html_text(item.get("title", ""))
            description = clean_html_text(item.get("description", ""))

            if not is_moa_keyword_related(title, description, keyword):
                continue

            matched = match_phishing_keywords(f"{title} {description}")
            # Da Moa 전용 키워드(예: 전세사기)는 추적 목록에 없어도 선택 키워드로 표기
            if keyword and keyword not in matched:
                matched = [keyword] + matched
            analysis = analyze_crime_method(title, description, matched)
            seen.add(link)
            articles.append(
                {
                    "title": title,
                    "description": description,
                    "link": link,
                    "press": extract_press_name(item.get("originallink", "")),
                    "date": pub_date.strftime("%Y-%m-%d"),
                    "datetime": pub_date,
                    "keywords": matched,
                    "analysis": analysis,
                }
            )
        except Exception:
            continue

    articles.sort(key=lambda x: x["datetime"], reverse=True)
    return dedupe_articles_by_title(articles), None


@st.cache_data(ttl=NAVER_API_CACHE_TTL, show_spinner=False)
def fetch_phishing_news(client_id: str, client_secret: str, _cache_ver: int = 57):
    """
    1) 피싱·보이스피싱·금융사기 등 관련 키워드로 뉴스 전체 수집
    2) 수집 기사 중 범죄 행위·수단이 드러나는 기사만 추려 재검색 키워드 분석
    3) 상위 10개 행위 키워드로 재검색 후 병합 (백서·목록용)
    피싱 주의보: 1단계 피싱 관련 기사 중 홍보·표창 등만 제외해 집계 (실제사례 필터 미적용)
    """
    headers = naver_news_search_headers(client_id, client_secret)

    def search_news(query: str, display: int = 100) -> tuple[list, str | None]:
        try:
            res = requests.get(
                NAVER_NEWS_SEARCH_URL,
                headers=headers,
                params=naver_news_search_params(query, display=display),
                timeout=10,
            )
            res.raise_for_status()
            return res.json().get("items", []), None
        except requests.HTTPError as e:
            return [], format_naver_search_error(query, e)
        except requests.RequestException as e:
            return [], f"'{query}' 네트워크 오류: {e}"

    errors = []
    now_naive = datetime.now()
    past_month = now_naive - timedelta(days=30)
    past_alert = now_naive - timedelta(days=ALERT_LOOKBACK_DAYS)

    generic_type_words = tuple(PHISHING_RELATED_TERMS)

    def items_to_articles(raw_items: list, require_type: bool = True) -> list[dict]:
        articles = []
        seen = set()
        for item in raw_items:
            try:
                link = item.get("link") or item.get("originallink") or ""
                if not link or link in seen:
                    continue

                pub_date = parsedate_to_datetime(item["pubDate"]).replace(tzinfo=None)
                if pub_date < past_month:
                    continue

                title = clean_html_text(item.get("title", ""))
                description = clean_html_text(item.get("description", ""))
                combined = f"{title} {description}"

                if contains_excluded(combined):
                    continue

                matched = match_phishing_keywords(combined)
                if require_type and not matched and not any(
                    w in combined for w in generic_type_words
                ):
                    continue

                analysis = analyze_crime_method(title, description, matched)
                tactics = analysis["tactics"]
                score = relevance_score(title, matched, tactics, description)
                seen.add(link)
                articles.append(
                    {
                        "title": title,
                        "description": description,
                        "link": link,
                        "press": extract_press_name(item.get("originallink", "")),
                        "date": pub_date.strftime("%Y-%m-%d"),
                        "datetime": pub_date,
                        "keywords": matched,
                        "analysis": analysis,
                        "score": score,
                        "tactics": tactics,
                    }
                )
            except Exception:
                continue
        return articles

    # --- 1단계: 피싱·사기 관련 키워드 전체 검색 ---
    seed_raw: list = []
    for seed_query in ALL_NEWS_SCRAP_QUERIES:
        items, seed_err = search_news(seed_query, display=SEED_QUERY_DISPLAY)
        if seed_err:
            errors.append(seed_err)
        seed_raw.extend(items)

    all_phishing_articles = items_to_articles(seed_raw, require_type=False)
    all_phishing_articles = [
        a
        for a in all_phishing_articles
        if is_phishing_related_article(a["title"], a["description"], a["keywords"])
    ]

    # --- 2단계: 범죄 행위·수단이 드러나는 기사만 추려 키워드 분석 ---
    crime_action_articles = []
    for article in all_phishing_articles:
        primary = (article.get("keywords") or [None])[0]
        tactics = article.get("tactics") or detect_modus_operandi(
            f"{article['title']} {article['description']}", primary
        )
        if is_crime_action_article(
            article["title"], article["description"], article["keywords"], tactics
        ):
            article["tactics"] = tactics
            crime_action_articles.append(article)

    keyword_rank = scrape_keyword_frequency(
        crime_action_articles,
        top_n=10,
        exclude_keywords=GENERIC_SEED_EXCLUDE,
        crime_only=True,
    )
    top_keywords = filter_keywords_for_research(keyword_rank)

    # 피싱 주의보: 실제사례·범죄행위 필터 없이, 홍보·표창 등만 제외
    # 링크는 달라도 제목이 같으면 같은 기사로 보고, 횟수·목록 건수를 맞춘다
    alert_articles = dedupe_articles_by_title(
        [
            a
            for a in all_phishing_articles
            if a["datetime"] >= past_alert
            and not is_alert_promo_excluded_article(
                a["title"], a.get("description", ""), a.get("link", "")
            )
        ]
    )
    alert_keyword_rank = scrape_keyword_frequency(
        alert_articles,
        top_n=10,
        exclude_keywords=GENERIC_SEED_EXCLUDE,
        crime_only=True,
    )
    alert_crime_hits: list[str] = []
    for article in alert_articles:
        alert_crime_hits.extend(article.get("keywords") or [])

    # --- 3단계: 행위 키워드로 재검색 ---
    raw_second = []
    for kw in top_keywords:
        got_any = False
        for query in build_research_queries(kw):
            items, err = search_news(query, display=50)
            if err:
                errors.append(err)
            elif items:
                raw_second.extend(items)
                got_any = True
        if not got_any:
            items, err2 = search_news(kw, display=50)
            if err2:
                errors.append(err2)
            else:
                raw_second.extend(items)

    second_articles = items_to_articles(raw_second, require_type=False)
    second_articles = [
        a
        for a in second_articles
        if is_phishing_related_article(a["title"], a["description"], a["keywords"])
    ]

    merged_by_link = {}
    for article in all_phishing_articles + second_articles:
        prev = merged_by_link.get(article["link"])
        if prev is None or article["score"] > prev["score"]:
            merged_by_link[article["link"]] = article
    merged_articles = list(merged_by_link.values())

    all_news = [
        a
        for a in merged_articles
        if is_financial_fraud_article(a["title"], a["description"], a["keywords"])
        and not is_promo_or_policy_article(f"{a['title']} {a['description']}")
        and not is_editorial_or_opinion_article(
            a["title"], a["description"], a.get("link", "")
        )
    ]
    all_news.sort(key=lambda x: x["datetime"], reverse=True)

    method_news = []
    for article in merged_articles:
        primary = (article.get("keywords") or [None])[0]
        tactics = article.get("tactics") or detect_modus_operandi(
            f"{article['title']} {article['description']}", primary
        )
        if not is_crime_action_article(
            article["title"], article["description"], article["keywords"], tactics
        ):
            continue
        article["tactics"] = tactics
        # 분석 문구·신뢰도를 강화 규칙으로 재생성
        article["analysis"] = analyze_crime_method(
            article["title"], article["description"], article.get("keywords") or []
        )
        if is_editorial_or_opinion_article(
            article["title"], article["description"], article.get("link", "")
        ):
            continue
        if is_promo_or_policy_article(
            f"{article['title']} {article['description']}"
        ):
            continue
        if is_police_station_promo_article(
            article["title"], article.get("description", "")
        ):
            continue
        if is_method_focused_article(
            article["title"], article["description"], article["keywords"], tactics
        ):
            method_news.append(article)

    method_news.sort(key=lambda x: (x["score"], x["datetime"]), reverse=True)
    method_news = dedupe_articles_by_title(method_news)

    return (
        method_news,
        all_news,
        alert_crime_hits,
        errors,
        alert_keyword_rank,
        alert_articles,
    )


# ---------------------------------------------------------------------------
# 인증 / 데이터 로드
# ---------------------------------------------------------------------------
client_id, client_secret = get_naver_credentials()

if not client_id or not client_secret:
    st.error(
        "네이버 API 인증 정보가 없습니다. "
        "`.streamlit/secrets.toml` 에 Client ID/Secret을 입력하세요."
    )
    st.stop()

with st.spinner(
    "보이스피싱, 스미싱, 딥페이크 등 전기통신금융사기 뉴스를 수집·분석 중입니다."
):
    (
        news_list,
        all_news_list,
        alert_crime_hits,
        fetch_errors,
        alert_keywords,
        alert_news,
    ) = fetch_phishing_news(client_id, client_secret, _cache_ver=57)

if fetch_errors and not news_list:
    st.error("뉴스 데이터를 가져오지 못했습니다.\n\n- " + "\n- ".join(fetch_errors))
    st.stop()
elif fetch_errors:
    st.warning("일부 검색만 실패했습니다: " + " / ".join(fetch_errors))

crime_counter = Counter(alert_crime_hits)

# 주의보 키워드 하이퍼링크(?alert_moa=&n=) — nonce로 한 번만 적용
_alert_moa_q = st.query_params.get("alert_moa")
_alert_moa_n = st.query_params.get("n")
if isinstance(_alert_moa_q, (list, tuple)):
    _alert_moa_q = _alert_moa_q[0] if _alert_moa_q else None
if isinstance(_alert_moa_n, (list, tuple)):
    _alert_moa_n = _alert_moa_n[0] if _alert_moa_n else None
if _alert_moa_q:
    _nonce = str(_alert_moa_n or "")
    _consumed = str(st.session_state.get("moa_alert_consumed_nonce") or "")
    if _nonce and _nonce != _consumed:
        trigger_moa_from_alert(str(_alert_moa_q))
        st.session_state.moa_alert_consumed_nonce = _nonce
        try:
            st.session_state.moa_alert_link_nonce = int(_nonce) + 1
        except ValueError:
            st.session_state.moa_alert_link_nonce = (
                int(st.session_state.get("moa_alert_link_nonce") or 1) + 1
            )
    for _qp in ("alert_moa", "n"):
        if _qp in st.query_params:
            try:
                del st.query_params[_qp]
            except Exception:
                pass

# ---------------------------------------------------------------------------
# 홈 화면: 긴급 주의보
# ---------------------------------------------------------------------------
st.caption("제작 : 광주동부경찰서 범죄예방대응과")
st.markdown(
    '<h1 class="phishing-mobile-title">👮‍♂️피싱 범죄 Da Moa👮‍♀️</h1>',
    unsafe_allow_html=True,
)
st.write(
    "보이스피싱, 스미싱, 딥페이크 등 최신 전기통신금융사기 뉴스를 수집·분석하여 "
    "실제 범행 수법과 피해 사례를 확인하고, 이를 바탕으로 한 최근 피싱범죄 키워드와 "
    "예방 정보를 함께 안내해 드립니다."
)
st.caption("뉴스 검색: **네이버 OPEN API** (Search API)")

if alert_keywords:
    tied = select_tied_top_keywords(alert_keywords)
    top_crimes = [kw for kw, _ in tied]
    top_count = tied[0][1]
    alert = build_urgent_alert_info(top_crimes, top_count, alert_news)
    render_phishing_alert_block(alert)
elif crime_counter:
    ranked = crime_counter.most_common()
    tied = select_tied_top_keywords(ranked)
    top_crimes = [kw for kw, _ in tied]
    top_count = tied[0][1]
    alert = build_urgent_alert_info(top_crimes, top_count, alert_news)
    render_phishing_alert_block(alert)
else:
    st.success("🟢 최근 2주간 두드러진 피싱 키워드는 없습니다.")

# 주의보 키워드 선택 시 — 예방 포인트 바로 아래 기사
if st.session_state.get("moa_search_source") == "alert":
    _alert_kw = (
        st.session_state.get("moa_alert_display_kw")
        or st.session_state.get("moa_active_keyword")
    )
    if _alert_kw:
        _alert_arts = filter_articles_by_alert_keyword(alert_news, _alert_kw)
        render_alert_inline_articles(_alert_arts, _alert_kw)

st.divider()

# ---------------------------------------------------------------------------
# 파트 1: 수법·사건 중심 뉴스
# ---------------------------------------------------------------------------
render_backseo_section_header(len(news_list) if news_list else 0)

if news_list:
    render_naver_api_attribution()
    st.caption(
        "※ 각 기사 아래 **범행 수법 분석·예방**은 본 서비스가 공개 요약을 바탕으로 자동 정리한 내용입니다."
    )
    st.markdown(
        '<div id="method-analysis-section"></div>'
        '<p class="phishing-backseo-card-label">최신 수법 분석 및 예방</p>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("method_list_closed"):
        if st.button("수법 기사 다시 보기", key="method_list_reopen"):
            st.session_state.method_list_closed = False
            st.session_state.display_count = 3
            st.session_state.pop("method_list_close_cb", None)
            st.rerun()
    else:
        focus_method_idx = st.session_state.pop("scroll_to_method_article", None)
        current_visible_news = news_list[: st.session_state.display_count]

        for idx, news in enumerate(current_visible_news, 1):
            if focus_method_idx is not None and idx == focus_method_idx:
                st.markdown(
                    '<div id="method-article-focus"></div>', unsafe_allow_html=True
                )
            analysis = news["analysis"]
            with st.container(border=True):
                st.markdown(f"**{idx}. [{news['title']}]({news['link']})**")
                st.caption(
                    f"📢 {news['press']} | 🗓️ {news['date']} | "
                    f"🏷️ {analysis['primary']}"
                    + (
                        f" · {' · '.join(analysis['keywords'][1:])}"
                        if len(analysis["keywords"]) > 1
                        else ""
                    )
                )

                if analysis.get("snippet"):
                    st.write(analysis["snippet"])

                render_app_analysis_block(analysis)

        if focus_method_idx is not None:
            scroll_to_dom_id(
                "method-article-focus",
                delay_ms=0,
                retries=_MORE_SCROLL_RETRIES,
                offset_px=32,
            )

        remaining = len(news_list) - st.session_state.display_count
        if remaining > 0:
            add_count = min(10, remaining)
            method_action = render_more_with_close(
                more_label=f"🔽 수법 기사 더보기 ({add_count}개 추가)",
                more_key="more_method",
                close_key="method_list_close_cb",
            )
        else:
            method_action = render_more_with_close(
                more_label=None,
                more_key=None,
                close_key="method_list_close_cb",
                done_caption=f"수법 중심 기사 {len(news_list)}건을 모두 표시했습니다.",
            )
        if method_action == "more":
            prev_count = st.session_state.display_count
            st.session_state.display_count = prev_count + 10
            st.session_state.scroll_to_method_article = prev_count + 1
            st.session_state["_clear_method_list_close_cb"] = True
            st.rerun()
        elif method_action == "close":
            close_method_article_list()
            st.rerun()
else:
    st.info("수법·사건 조건에 맞는 뉴스 기사가 없습니다.")

st.divider()

# ---------------------------------------------------------------------------
# 파트 2: Da Moa — 키워드 선택 시 1회 검색
# ---------------------------------------------------------------------------
if st.session_state.pop("scroll_to_moa", False):
    scroll_to_dom_id(
        "moa-section",
        delay_ms=0,
        retries=_SECTION_SCROLL_RETRIES,
        fallback_selector=".phishing-moa-hero",
        offset_px=72,
    )

st.markdown('<div id="moa-section"></div>', unsafe_allow_html=True)
render_moa_section_header()

# 직접 검색·닫기 예약값 — selectbox 위젯 생성 전에 session_state 반영
_pending_custom = st.session_state.pop("moa_pending_custom", None)
if _pending_custom:
    st.session_state.moa_active_keyword = _pending_custom
    st.session_state.moa_search_source = "custom"
    st.session_state.moa_display_count = 5
    st.session_state.moa_last_picked = None
    st.session_state.moa_keyword_picker = None
    st.session_state.moa_custom_chip = _pending_custom
    st.session_state.moa_custom_input = _pending_custom
    st.session_state.pop("moa_from_alert_nav", None)
    st.session_state.pop("moa_alert_display_kw", None)
    st.session_state.pop("moa_pending_clear_picker", None)
    st.session_state.pop("moa_pending_clear_custom_chip", None)
    st.session_state.scroll_to_moa_articles = True

if st.session_state.pop("moa_pending_clear_picker", False):
    st.session_state.moa_keyword_picker = None
    st.session_state.moa_last_picked = None

if st.session_state.pop("moa_pending_clear_custom_input", False):
    st.session_state.moa_custom_input = ""

if st.session_state.pop("moa_pending_clear_custom_chip", False):
    st.session_state.pop("moa_custom_chip", None)

# 주의보 기사는 선택창에 넣지 않음 — 열려 있는 동안 picker를 비워 둠
if st.session_state.get("moa_search_source") == "alert":
    st.session_state.moa_keyword_picker = None
    st.session_state.moa_last_picked = None

st.markdown(
    '<div id="moa-keyword-picker-section"></div>'
    '<p class="phishing-moa-picker-hint">📌 수법·유형 키워드를 선택해 주세요</p>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div id="moa-keyword-select-marker"></div>',
    unsafe_allow_html=True,
)

picked = st.selectbox(
    "키워드",
    MOA_KEYWORDS,
    index=None,
    placeholder="키워드 선택",
    label_visibility="collapsed",
    key="moa_keyword_picker",
    on_change=on_moa_keyword_picker_change,
)

st.markdown(
    '<p class="phishing-moa-picker-hint">🔎 또는 검색어를 직접 입력해 주세요</p>',
    unsafe_allow_html=True,
)

# 검색 완료 후 — 키워드 selectbox와 동일하게 창 안쪽 X로 지우기
_custom_active_q = (
    st.session_state.get("moa_active_keyword")
    if st.session_state.get("moa_search_source") == "custom"
    else None
)
if _custom_active_q:
    # index=None + placeholder → 선택창 내부에 clear(X) 표시
    st.session_state.moa_custom_chip = _custom_active_q
    st.selectbox(
        "직접 검색어",
        options=[_custom_active_q],
        index=None,
        placeholder="검색어",
        label_visibility="collapsed",
        key="moa_custom_chip",
        on_change=on_moa_custom_chip_change,
    )
else:
    # form + Enter 제출 — 입력칸 위 / 검색 버튼 아래 (모바일 잘림 없음)
    with st.form("moa_custom_search_form", clear_on_submit=False, border=False):
        st.text_input(
            "직접 검색",
            placeholder="예: 노쇼, 대포통장 등",
            label_visibility="collapsed",
            key="moa_custom_input",
            max_chars=40,
        )
        moa_custom_clicked = st.form_submit_button(
            "🔍 검색",
            use_container_width=True,
        )

    if moa_custom_clicked:
        custom_q = (st.session_state.get("moa_custom_input") or "").strip()
        if len(custom_q) < 2:
            st.warning("검색어는 2자 이상 입력해 주세요.")
        else:
            st.session_state.moa_pending_custom = custom_q
            st.rerun()

selected_kw = st.session_state.get("moa_active_keyword") or picked
moa_articles: list[dict] = []
moa_error: str | None = None
moa_crime_only = False
moa_from_alert = st.session_state.get("moa_search_source") == "alert"

if selected_kw and moa_from_alert:
    # 주의보 기사는 예방 포인트 아래에서 이미 표시
    display_kw = st.session_state.get("moa_alert_display_kw") or selected_kw
    st.info(
        f"주의 키워드 「{display_kw}」 기사 목록은 위 **예방 포인트 아래**에서 확인할 수 있습니다."
    )
    st.session_state.pop("moa_from_alert_nav", None)
    st.session_state.pop("moa_crime_only", None)
elif selected_kw:
    with st.spinner(f"「{selected_kw}」 관련 기사 불러오는 중…"):
        moa_articles, moa_error = fetch_moa_keyword_news(
            client_id, client_secret, selected_kw
        )
    # 체크박스 렌더 전 — 직전 선택값으로 건수·필터 반영
    moa_crime_only = bool(st.session_state.get("moa_crime_only", False))
else:
    # 키워드 없을 때 범죄기사 체크 상태가 남아 orphan 오류 나지 않게 정리
    st.session_state.pop("moa_crime_only", None)

if moa_crime_only and moa_articles:
    moa_articles = [
        article
        for article in moa_articles
        if is_moa_crime_only_article(
            article.get("title") or "",
            article.get("description", ""),
            article.get("keywords"),
        )
    ]

if selected_kw and not moa_from_alert:
    moa_more_key = _moa_more_button_key(selected_kw)
    st.session_state.moa_more_key_last = moa_more_key
    if moa_error:
        st.markdown('<div id="moa-articles-section"></div>', unsafe_allow_html=True)
        st.error(moa_error)
        discard_widget_key(moa_more_key)
        st.session_state.pop("moa_crime_only", None)
    else:
        # 「최신 기사 N건」 바로 옆에 범죄기사 체크 (오른쪽 여백으로 붙임)
        label_col, crime_col, _pad = st.columns(
            [3.1, 1.15, 3.2], vertical_alignment="center"
        )
        with label_col:
            st.markdown(
                f'<div class="phishing-moa-label-row">'
                f'<p class="phishing-moa-card-label" id="moa-articles-section">'
                f"「{html.escape(str(selected_kw))}」 최신 기사 "
                f"{len(moa_articles)}건</p></div>",
                unsafe_allow_html=True,
            )
        with crime_col:
            moa_crime_only = st.checkbox(
                "범죄기사",
                key="moa_crime_only",
                help=(
                    "제목에 수사·사법 표현이 있거나, "
                    "범행 표현과 사건 신호가 함께 있는 기사만 남깁니다."
                ),
                on_change=on_moa_crime_only_change,
            )
        if moa_crime_only:
            st.caption(
                "제목 기준 필터 — "
                "① 검거·송치·구속·체포·적발·기소·재판·선고·피의자·일당 등 "
                "수사·사법 표현이 있는 기사, 또는 "
                "② 편취·수법·기승·급증 등과 "
                "일당·속아·억원·피해액 등 사건 신호가 **함께** 있는 기사만 표시합니다."
            )

        if moa_articles:
            focus_moa_idx = st.session_state.pop("scroll_to_moa_article", None)
            visible = moa_articles[: st.session_state.moa_display_count]
            render_naver_api_attribution()
            for idx, news in enumerate(visible, 1):
                if focus_moa_idx is not None and idx == focus_moa_idx:
                    st.markdown(
                        '<div id="moa-article-focus"></div>', unsafe_allow_html=True
                    )
                keywords = news.get("keywords") or []
                analysis = news.get("analysis") or {}
                kw_label = (
                    " · ".join(keywords)
                    if keywords
                    else (analysis.get("primary") or selected_kw)
                )
                with st.container(border=True):
                    st.markdown(f"**{idx}. [{news['title']}]({news['link']})**")
                    st.caption(
                        f"📢 {news['press']} | 🗓️ {news['date']} | 🏷️ {kw_label}"
                    )
                    if news.get("description"):
                        snippet = news["description"]
                        st.write(snippet[:160] + ("…" if len(snippet) > 160 else ""))

            if focus_moa_idx is not None:
                scroll_to_dom_id(
                    "moa-article-focus",
                    delay_ms=0,
                    retries=_MORE_SCROLL_RETRIES,
                    offset_px=32,
                )

            remaining_moa = len(moa_articles) - st.session_state.moa_display_count
            if remaining_moa > 0:
                add_count = min(10, remaining_moa)
                moa_action = render_more_with_close(
                    more_label=f"🔽 「{selected_kw}」 더보기 ({add_count}개 추가)",
                    more_key=moa_more_key,
                    close_key="moa_list_close_cb",
                )
            else:
                discard_widget_key(moa_more_key)
                moa_action = render_more_with_close(
                    more_label=None,
                    more_key=None,
                    close_key="moa_list_close_cb",
                    done_caption=(
                        f"「{selected_kw}」 기사 {len(moa_articles)}건을 모두 표시했습니다."
                    ),
                )
            if moa_action == "more":
                prev_count = st.session_state.moa_display_count
                st.session_state.moa_display_count = prev_count + 10
                st.session_state.scroll_to_moa_article = prev_count + 1
                st.session_state["_clear_moa_list_close_cb"] = True
                st.rerun()
            elif moa_action == "close":
                close_moa_keyword_list()
                st.rerun()
        else:
            if moa_crime_only:
                st.info(
                    f"「{selected_kw}」 관련 기사 중 범죄기사 조건에 맞는 기사가 없습니다."
                )
            else:
                st.info(f"「{selected_kw}」 관련 기사가 없습니다.")
            discard_widget_key(moa_more_key)
            moa_action = render_more_with_close(
                more_label=None,
                more_key=None,
                close_key="moa_list_close_cb",
                done_caption="목록을 닫으려면 오른쪽 닫기를 선택하세요.",
            )
            if moa_action == "close":
                close_moa_keyword_list()
                st.rerun()

    # 키워드·직접 검색 직후 제목(최신 기사 N건)이 보이도록 이동
    if st.session_state.pop("scroll_to_moa_articles", False):
        scroll_to_dom_id(
            "moa-articles-section",
            delay_ms=50,
            retries=_SECTION_SCROLL_RETRIES,
            offset_px=96,
            grace_ms=700,
        )

st.caption(
    "본 서비스는 **민간 범죄 예방 안내용**이며, 수사기관·금융당국의 공식 경보·긴급 통보를 "
    "대체하지 않습니다."
)
st.caption(
    "기사 **제목·요약**은 **네이버 OPEN API** 검색 결과이며, **저작권은 각 언론사**에 있습니다. "
    "기사 전문은 원문 링크를 통해 해당 언론사에서 열람해 주세요."
)
st.caption("무단 복제·전재·배포를 금지하며, 의심 정황은 **112** 또는 **1332**로 신고해 주세요.")

# 닫기 후 각 섹션 화면으로 최종 복귀 (위젯 포커스보다 늦게)
if st.session_state.pop("scroll_stay_alert_close", False):
    scroll_to_alert_screen()
if st.session_state.pop("scroll_stay_method_close", False):
    scroll_to_method_screen()
if st.session_state.pop("scroll_stay_moa_close", False):
    scroll_to_moa_screen()

# 주의보 키워드 클릭 → 기사 목록으로 화면 이동
_scroll_alert_left = int(st.session_state.get("scroll_to_alert_news") or 0)
if _scroll_alert_left > 0:
    st.session_state.scroll_to_alert_news = _scroll_alert_left - 1
    scroll_to_dom_id(
        "alert-news-section",
        delay_ms=100,
        retries=(0, 250, 600),
        offset_px=88,
        grace_ms=180,
    )
