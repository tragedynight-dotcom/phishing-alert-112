import json
import re
from collections import Counter
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components

# ---------------------------------------------------------------------------
# 1. 페이지 설정
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="대국민 피싱 범죄 예방 주의보",
    page_icon="🚨",
    layout="centered",
)

if "alert_shown" not in st.session_state:
    st.session_state.alert_shown = False
if "display_count" not in st.session_state:
    st.session_state.display_count = 5
if "display_count_all" not in st.session_state:
    st.session_state.display_count_all = 5
if "notify_ready" not in st.session_state:
    st.session_state.notify_ready = False

# 추적할 피싱 수법 키워드 (긴 키워드 우선 매칭)
PHISHING_KEYWORDS = [
    "정부지원금 사기",
    "렌터카 사기",
    "렌터카사기",
    "렌탈 사기",
    "렌탈사기",
    "카셰어링 사기",
    "신종 사기",
    "로맨스스캠",
    "메신저피싱",
    "몸캠피싱",
    "보이스피싱",
    "기관사칭",
    "지인사칭",
    "투자사기",
    "전세사기",
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
    "투자사기": {
        "how": "고수익·리딩방·가짜 거래소로 유인해 투자금을 편취합니다.",
        "watch": "원금 보장·고수익 확정 홍보, 텔레그램·카톡 리딩방 유도에 주의하세요.",
    },
    "전세사기": {
        "how": "허위·중복 계약, 선순위 권리 미고지 등으로 보증금을 가로챕니다.",
        "watch": "등기·확정일자·전세보증 가입 여부를 계약 전 반드시 확인하세요.",
    },
    "기관사칭": {
        "how": "검찰·경찰·금감원·은행 등 공공·금융기관을 사칭해 개인정보와 돈을 요구합니다.",
        "watch": "기관은 전화로 계좌이체·현금 전달을 요구하지 않습니다.",
    },
    "정부지원금 사기": {
        "how": "지원금·환급·보조금 지급을 미끼로 개인정보·수수료 입금을 유도합니다.",
        "watch": "정부 지원금은 문자 링크로 신청받지 않습니다. 공식 누리집에서 확인하세요.",
    },
    "렌탈 사기": {
        "how": "렌터카·장비·명품 등 렌탈 명목으로 계약금·보증금·연장 요금을 받은 뒤 차량·물품을 돌려주지 않거나 추가 비용을 요구합니다.",
        "watch": "본인 명의 렌탈·대출·계약 대행 제안, 선입금 요구는 사기일 가능성이 큽니다.",
    },
    "렌탈사기": {
        "how": "렌터카·장비·명품 등 렌탈 명목으로 계약금·보증금·연장 요금을 받은 뒤 차량·물품을 돌려주지 않거나 추가 비용을 요구합니다.",
        "watch": "본인 명의 렌탈·대출·계약 대행 제안, 선입금 요구는 사기일 가능성이 큽니다.",
    },
    "렌터카 사기": {
        "how": "렌터카 대여·연장·훼손·범칙금 등을 핑계로 보증금·위약금·추가 요금을 요구하거나, 명의 대여 후 차량을 돌려받지 않습니다.",
        "watch": "렌터카 명의 대여·대행 제안, 선입금·보증금 송금 요구는 사기일 가능성이 큽니다.",
    },
    "렌터카사기": {
        "how": "렌터카 대여·연장·훼손·범칙금 등을 핑계로 보증금·위약금·추가 요금을 요구하거나, 명의 대여 후 차량을 돌려받지 않습니다.",
        "watch": "렌터카 명의 대여·대행 제안, 선입금·보증금 송금 요구는 사기일 가능성이 큽니다.",
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
    "금융사기": {
        "how": "대출·투자·환급·명의 변경 등을 핑계로 금융정보·수수료·송금을 요구합니다.",
        "watch": "선입금·수수료 선납을 요구하는 대출·환급 안내는 사기입니다.",
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
    return f"최근 보도에서는 **{' / '.join(top_tactics)}** 방식이 자주 언급됩니다."


def build_urgent_alert_info(
    top_crime: str, top_count: int, news_list: list[dict]
) -> dict:
    """긴급 주의보·OS 알림에 쓸 키워드·범행 진행 방식 문구를 만듭니다."""
    profile = ALERT_PROFILES.get(
        top_crime,
        {
            "how": "피싱·사기 피해를 유도하는 연락·링크·송금 요구가 최근 보도에서 반복되고 있습니다.",
            "watch": "금전·개인정보 요구, 링크 클릭·앱 설치 유도가 있으면 일단 중단하고 공식 경로로 확인하세요.",
        },
    )
    how_base = profile.get("how", "")
    news_hint = summarize_crime_from_news(top_crime, news_list)
    how_full = f"{how_base} {news_hint}".strip() if news_hint else how_base

    push_msg = (
        f"▶ 최다 키워드: {top_crime} ({top_count}회)\n"
        f"▶ 진행 방식: {how_base}"
    )
    if len(push_msg) > 240:
        push_msg = push_msg[:237] + "…"

    return {
        "keyword": top_crime,
        "count": top_count,
        "how": how_base,
        "how_full": how_full,
        "watch": profile.get("watch", ""),
        "push_title": "🚨 [피싱 주의보]",
        "push_msg": push_msg,
    }

# 기사 본문에서 구체적 범행 수단을 찾는 단서
MODUS_CUES = [
    ("검찰·경찰 등 수사기관 사칭", ["검찰", "경찰", "수사관", "체포영장", "공조"]),
    ("금융감독원·은행 등 금융기관 사칭", ["금감원", "금융감독", "은행 직원", "카드사", "명의도용"]),
    ("가족·지인 사칭 급전 요구", ["가족", "지인", "아들", "딸", "급전", "폰 고장"]),
    ("악성 문자·링크 클릭 유도", ["문자", "링크", "URL", "악성앱", "설치 유도"]),
    ("QR코드 스캔 유도", ["QR", "큐싱", "스캔"]),
    ("메신저(카톡 등)로 금전·상품권 요구", ["카카오톡", "카톡", "메신저", "상품권", "쿠폰"]),
    ("원격제어 앱 설치 요구", ["원격", "팀뷰어", "AnyDesk", "앱 설치", "화면공유"]),
    ("고수익 투자·리딩방 유인", ["투자", "리딩", "수익률", "가상자산", "코인", "주식 리딩"]),
    ("영상·딥페이크 협박·사칭", ["딥페이크", "영상 유포", "몸캠", "합성"]),
    ("지원금·환급 미끼", ["지원금", "환급", "보조금", "재난지원", "신청 링크"]),
    ("전세·임대차 계약 관련 편취", ["전세", "보증금", "임대차", "등기"]),
    ("렌탈·렌터카·카셰어링 명의 대여 후 미반납·추가금 요구", ["렌탈", "렌터카", "카셰어링", "차량 공유", "명의 대여", "보증금", "연장 요금", "범칙금"]),
    ("신종·변형 수법 언급", ["신종 사기", "신종", "신종수법", "변형 수법"]),
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
)


def count_actual_case_signals(text: str) -> int:
    return sum(1 for word in ACTUAL_CASE_SIGNALS if word in text)


def is_promo_or_policy_article(text: str) -> bool:
    """대회·홍보·시책 추진 등 실제 사례가 아닌 기사."""
    if contains_excluded(text):
        return True

    case_hits = count_actual_case_signals(text)
    promo_hits = sum(1 for marker in PROMO_POLICY_MARKERS if marker in text)

    if any(word in text for word in ("공모전", "UCC", "경진대회", "콘테스트")):
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


def is_actual_case_article(
    title: str, description: str, keywords: list[str], tactics: list[str]
) -> bool:
    """실제 발생한 피해·범행 사례가 드러나는 기사."""
    combined = f"{title} {description}"
    if is_promo_or_policy_article(combined):
        return False

    case_hits = count_actual_case_signals(combined)
    strong_case_words = (
        "편취",
        "피해액",
        "피해자",
        "피해 금액",
        "속았",
        "속아",
        "속였",
        "송금",
        "이체",
        "당했다",
        "당해",
        "발생",
        "신고",
        "억원",
        "만원",
    )
    has_strong_case = any(word in combined for word in strong_case_words)

    if tactics and (case_hits >= 1 or has_strong_case):
        return True
    if case_hits >= 2:
        return True
    if case_hits >= 1 and has_strong_case:
        return True
    if has_strong_case and bool(keywords):
        return True
    return False


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
    combined = f"{title} {description}"
    substance = count_substance_hits(combined)
    title_focused = has_crime_type_in_title(title)
    method_words = any(
        w in combined
        for w in ("수법", "범행", "사칭", "유인", "편취", "갈취", "미끼", "유도")
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
            "투자사기",
            "전세사기",
            "렌탈 사기",
            "렌탈사기",
            "렌터카 사기",
            "렌터카사기",
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
    "렌터카 사기",
    "렌터카사기",
    "렌탈 사기",
    "렌탈사기",
    "카셰어링 사기",
    "신종 사기",
    "로맨스스캠",
    "메신저피싱",
    "몸캠피싱",
    "기관사칭",
    "지인사칭",
    "투자사기",
    "전세사기",
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
    "금융사기",
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
    "금융사기",
    "팀뷰어",
}

# 피싱·사기 전체 수집용 시드 검색어
PHISHING_SEED_QUERIES = (
    "피싱",
    "보이스피싱",
    "금융사기",
    "스미싱",
    "큐싱",
    "메신저피싱",
    "몸캠피싱",
    "기관사칭",
    "지인사칭",
    "투자사기",
    "전세사기",
    "로맨스스캠",
    "딥페이크",
    "정부지원금 사기",
    "렌탈 사기",
    "렌터카 사기",
    "신종 사기",
    "전화금융사기",
)
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
# '기승'·'신종' 결합 검색 — 급증·신종 수법 보도 수집
FRAUD_MODIFIER_BASE_QUERIES = (
    "보이스피싱",
    "금융사기",
    "피싱",
    "스미싱",
    "큐싱",
    "메신저피싱",
    "몸캠피싱",
    "투자사기",
    "전화금융사기",
    "대출사기",
    "가상자산 사기",
    "리딩방 사기",
    "기관사칭",
    "지인사칭",
    "렌탈 사기",
    "전세사기",
    "로맨스스캠",
    "딥페이크",
)
FRAUD_SEARCH_MODIFIERS = ("기승", "신종")
MODIFIER_FRAUD_SEED_QUERIES = tuple(
    f"{query} {modifier}"
    for query in FRAUD_MODIFIER_BASE_QUERIES
    for modifier in FRAUD_SEARCH_MODIFIERS
)
ALL_NEWS_SCRAP_QUERIES = tuple(
    dict.fromkeys(
        PHISHING_SEED_QUERIES
        + FINANCIAL_FRAUD_EXTRA_QUERIES
        + MODIFIER_FRAUD_SEED_QUERIES
    )
)
PHISHING_RELATED_TERMS = set(PHISHING_SEED_QUERIES) | set(PHISHING_KEYWORDS) | {
    "피싱",
    "금융사기",
    "전화금융사기",
    "카셰어링",
    "렌탈사기",
    "렌터카사기",
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
    "칼럼]",
    "기고]",
    "사설]",
    "논설]",
    "기고문",
    "칼럼니스트",
    "오피니언",
    "데스크 칼럼",
    "Editorial",
    "기자수첩",
    "시론·",
    "사설·",
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
        if len(selected) >= 10:
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
    if re.search(r"\[(기고|칼럼|사설|논설|오피니언|시론|기고문|데스크)\]", title):
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
    """범죄 행위 키워드로 피싱·사기 관련 재검색 쿼리를 만듭니다."""
    queries = [f"{seed} {action_keyword}" for seed in PRIMARY_RESEARCH_SEEDS]
    for seed in PRIMARY_RESEARCH_SEEDS:
        for modifier in FRAUD_SEARCH_MODIFIERS:
            queries.append(f"{seed} {action_keyword} {modifier}")
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

        # 시드·일반 표현 제거 (복합 수법명은 allowlist에서 긴 구문 우선 매칭)
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
                # 표시용 대표 표기는 allowlist 원문
                counter[allowlist.get(key, phrase)] += hits
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


def detect_modus_operandi(text: str) -> list[str]:
    hits = []
    for label, cues in MODUS_CUES:
        if any(cue.lower() in text.lower() if cue.isascii() else cue in text for cue in cues):
            hits.append(label)
    return hits


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
    tactics = detect_modus_operandi(combined)
    if tactics:
        how_detail = (
            f"이 기사에서는 **{primary}** 유형으로 보이며, "
            f"구체적으로 **{' / '.join(tactics)}** 방식이 언급됩니다. "
            f"{profile['how']}"
        )
    else:
        how_detail = (
            f"이 기사는 **{primary}** 관련 보도로 분석됩니다. {profile['how']}"
        )
    return {
        "primary": primary,
        "keywords": keywords,
        "tactics": tactics,
        "how_detail": how_detail,
        "watch": profile["watch"],
        "snippet": description[:180] + ("…" if len(description) > 180 else ""),
    }


def build_home_alert_widget(
    title: str, message: str, top_crime: str, how_detail: str, top_count: int
) -> str:
    """
    Streamlit components.html 은 iframe 안에서 실행되어 Notification 이 막히는 경우가 많음.
    → 부모 창(window.parent)의 Notification 을 사용하고, 클릭 제스처로 권한을 받습니다.
    """
    title_js = json.dumps(title, ensure_ascii=False)
    message_js = json.dumps(message, ensure_ascii=False)
    crime_js = json.dumps(top_crime, ensure_ascii=False)
    how_js = json.dumps(how_detail, ensure_ascii=False)
    count_js = json.dumps(top_count, ensure_ascii=False)
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8" />
      <style>
        body {{
          margin: 0; font-family: "Segoe UI", "Malgun Gothic", sans-serif;
          background: linear-gradient(135deg, #7f1d1d 0%, #b91c1c 55%, #dc2626 100%);
          color: #fff; border-radius: 12px; overflow: hidden;
        }}
        .wrap {{ padding: 16px 18px; }}
        h3 {{ margin: 0 0 8px; font-size: 18px; }}
        p {{ margin: 0 0 12px; font-size: 14px; line-height: 1.5; opacity: .95; }}
        .how {{ margin-top: 8px; font-size: 13px; line-height: 1.45; opacity: .92; }}
        button {{
          appearance: none; border: 0; cursor: pointer;
          background: #fff; color: #991b1b; font-weight: 700;
          padding: 10px 14px; border-radius: 8px; font-size: 14px;
        }}
        button:hover {{ background: #fee2e2; }}
        #status {{ display:block; margin-top:10px; font-size:12px; opacity:.9; min-height:1.2em; }}
      </style>
    </head>
    <body>
      <div class="wrap">
        <h3>🚨 홈 긴급 알림</h3>
        <p>
          <strong>최다 키워드:</strong> <span id="crime"></span>
          (<span id="count"></span>회)
        </p>
        <p class="how"><strong>범행 진행:</strong> <span id="how"></span></p>
        <p>아래 버튼을 누르면 OS 알림으로도 같은 내용을 받을 수 있습니다.</p>
        <button id="btn" type="button">🔔 알림 허용하고 주의보 받기</button>
        <span id="status"></span>
      </div>
      <script>
        const title = {title_js};
        const body = {message_js};
        const crime = {crime_js};
        const how = {how_js};
        const count = {count_js};
        document.getElementById("crime").textContent = crime;
        document.getElementById("how").textContent = how;
        document.getElementById("count").textContent = count;
        const statusEl = document.getElementById("status");

        function hostWindow() {{
          try {{
            if (window.parent && window.parent !== window && window.parent.Notification) {{
              return window.parent;
            }}
          }} catch (e) {{}}
          return window;
        }}

        function playBeep(w) {{
          try {{
            const AC = w.AudioContext || w.webkitAudioContext;
            if (!AC) return;
            const ctx = new AC();
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = "square";
            osc.frequency.value = 880;
            gain.gain.value = 0.04;
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start();
            setTimeout(() => {{ osc.stop(); ctx.close(); }}, 220);
          }} catch (e) {{}}
        }}

        function sendNotification() {{
          const w = hostWindow();
          if (!("Notification" in w)) {{
            statusEl.textContent = "이 브라우저는 시스템 알림을 지원하지 않습니다. 화면 주의보를 확인하세요.";
            return;
          }}
          const show = () => {{
            try {{
              new w.Notification(title, {{
                body,
                icon: "https://cdn-icons-png.flaticon.com/512/564/564619.png",
                requireInteraction: true,
                tag: "phishing-home-alert"
              }});
              playBeep(w);
              statusEl.textContent = "✅ 시스템 알림을 보냈습니다. (이미 허용된 경우 바로 표시됩니다)";
            }} catch (err) {{
              statusEl.textContent = "알림 표시 실패: " + err;
            }}
          }};

          if (w.Notification.permission === "granted") {{
            show();
          }} else if (w.Notification.permission === "denied") {{
            statusEl.textContent = "알림이 차단되어 있습니다. 브라우저 사이트 설정에서 알림을 허용해 주세요.";
          }} else {{
            w.Notification.requestPermission().then((permission) => {{
              if (permission === "granted") show();
              else statusEl.textContent = "알림 권한이 거부되었습니다. 브라우저 주소창 자물쇠 아이콘에서 허용할 수 있습니다.";
            }});
          }}
        }}

        document.getElementById("btn").addEventListener("click", sendNotification);

        // 이미 허용된 경우 홈 진입 시 자동 1회 시도
        (function autoIfGranted() {{
          const w = hostWindow();
          try {{
            if ("Notification" in w && w.Notification.permission === "granted") {{
              const key = "phishing_alert_" + crime;
              if (w.sessionStorage.getItem(key) !== "1") {{
                sendNotification();
                w.sessionStorage.setItem(key, "1");
              }} else {{
                statusEl.textContent = "이번 세션에서 이미 알림을 보냈습니다. 다시 받으려면 버튼을 누르세요.";
              }}
            }} else {{
              statusEl.textContent = "알림이 오지 않았다면 버튼을 한 번 눌러 권한을 허용해 주세요.";
            }}
          }} catch (e) {{
            statusEl.textContent = "알림이 오지 않았다면 버튼을 한 번 눌러 권한을 허용해 주세요.";
          }}
        }})();
      </script>
    </body>
    </html>
    """


@st.cache_data(ttl=600, show_spinner=False)
def fetch_phishing_news(client_id: str, client_secret: str, _cache_ver: int = 21):
    """
    1) 피싱·보이스피싱·금융사기 등 관련 키워드로 뉴스 전체 수집
    2) 수집 기사 중 범죄 행위·수단이 드러나는 기사만 추려 키워드·주의보 분석
    3) 행위 키워드로 재검색 후 병합
    """
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": client_id,
        "X-Naver-Client-Secret": client_secret,
    }

    def search_news(query: str, display: int = 100) -> tuple[list, str | None]:
        try:
            res = requests.get(
                url,
                headers=headers,
                params={"query": query, "display": display, "start": 1, "sort": "date"},
                timeout=10,
            )
            res.raise_for_status()
            return res.json().get("items", []), None
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            return [], f"'{query}' 검색 실패 (HTTP {status})"
        except requests.RequestException as e:
            return [], f"'{query}' 네트워크 오류: {e}"

    errors = []
    now_naive = datetime.now()
    past_month = now_naive - timedelta(days=30)

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

                tactics = detect_modus_operandi(combined)
                analysis = analyze_crime_method(title, description, matched)
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
        items, seed_err = search_news(seed_query, display=50)
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
        tactics = article.get("tactics") or detect_modus_operandi(
            f"{article['title']} {article['description']}"
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
    found_crimes = []
    for article in merged_articles:
        tactics = article.get("tactics") or detect_modus_operandi(
            f"{article['title']} {article['description']}"
        )
        if not is_crime_action_article(
            article["title"], article["description"], article["keywords"], tactics
        ):
            continue
        if is_method_focused_article(
            article["title"], article["description"], article["keywords"], tactics
        ):
            method_news.append(article)
            found_crimes.extend(article["keywords"])

    method_news.sort(key=lambda x: (x["score"], x["datetime"]), reverse=True)
    return method_news, all_news, found_crimes, errors, keyword_rank


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

with st.spinner(f"{SEED_SEARCH_LABEL} 피싱·사기 뉴스 수집 및 범죄 행위 분석 중..."):
    news_list, all_news_list, crime_hits, fetch_errors, derived_keywords = (
        fetch_phishing_news(client_id, client_secret, _cache_ver=21)
    )

if fetch_errors and not news_list and not all_news_list:
    st.error("뉴스 데이터를 가져오지 못했습니다.\n\n- " + "\n- ".join(fetch_errors))
    st.stop()
elif fetch_errors:
    st.warning("일부 검색만 실패했습니다: " + " / ".join(fetch_errors))

crime_counter = Counter(crime_hits)

# ---------------------------------------------------------------------------
# 홈 화면: 긴급 주의보 + 동작하는 시스템 알림
# ---------------------------------------------------------------------------
st.caption("제작 : 광주동부경찰서 범죄예방대응과")
st.title("👮‍♂️ 피싱 경보 112👮‍♀️")
st.write(
    f"{SEED_SEARCH_LABEL} 피싱·사기 관련 뉴스를 넓게 수집한 뒤, "
    "실제 피해·범행 사례가 드러나는 기사 위주로 정리해 주의보와 예방 정보를 안내합니다."
)

# 주의보는 키워드 분석 1위 우선, 없으면 기존 수법 카운터
if derived_keywords:
    top_crime, top_count = derived_keywords[0]
    alert = build_urgent_alert_info(top_crime, top_count, news_list)
    st.error(
        f"### 🚨 [피싱 주의보] 지금 가장 많이 등장한 키워드: **{alert['keyword']}** "
        f"({alert['count']}회)"
    )
    st.write(
        f"피싱 관련 보도에서 **{alert['count']}회**로 가장 많이 나타난 범죄 행위·수단입니다."
    )
    st.markdown(f"**🔎 범행 진행 방식:** {alert['how_full']}")
    if alert.get("watch"):
        st.info(f"예방 포인트: {alert['watch']}")

    components.html(
        build_home_alert_widget(
            alert["push_title"],
            alert["push_msg"],
            alert["keyword"],
            alert["how"],
            alert["count"],
        ),
        height=240,
    )
    st.toast(
        f"주의보: {alert['keyword']} — {alert['how'][:60]}{'…' if len(alert['how']) > 60 else ''}",
        icon="🚨",
    )
    st.session_state.alert_shown = True
elif crime_counter:
    top_crime, top_count = crime_counter.most_common(1)[0]
    alert = build_urgent_alert_info(top_crime, top_count, news_list)
    st.error(
        f"### 🚨 [피싱 주의보] 지금 가장 주의할 수법: **{alert['keyword']}** "
        f"({alert['count']}회)"
    )
    st.write(
        f"최근 한 달 보도 매칭 **{alert['count']}회**로 가장 집중되었습니다."
    )
    st.markdown(f"**🔎 범행 진행 방식:** {alert['how_full']}")
    if alert.get("watch"):
        st.info(f"예방 포인트: {alert['watch']}")

    components.html(
        build_home_alert_widget(
            alert["push_title"],
            alert["push_msg"],
            alert["keyword"],
            alert["how"],
            alert["count"],
        ),
        height=240,
    )
    st.toast(
        f"주의보: {alert['keyword']} — {alert['how'][:60]}{'…' if len(alert['how']) > 60 else ''}",
        icon="🚨",
    )
    st.session_state.alert_shown = True
else:
    st.success("🟢 최근 한 달간 특별히 급증하는 특정 피싱 키워드는 탐지되지 않았습니다.")

st.divider()

# ---------------------------------------------------------------------------
# 파트 1: 수법·사건 중심 뉴스
# ---------------------------------------------------------------------------
st.subheader("미리 알고 대비하는 피싱 범죄 백서")
st.caption(
    "피싱·사기 관련 기사 중 실제 피해·범행 사례가 드러나고, "
    "사칭·편취·계좌이체 등 범죄 행위·수단이 확인된 기사만 정리했습니다."
)

if news_list:
    current_visible_news = news_list[: st.session_state.display_count]

    for idx, news in enumerate(current_visible_news, 1):
        analysis = news["analysis"]
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

        st.markdown(f"**🔎 범행 수법 분석:** {analysis['how_detail']}")
        if analysis["tactics"]:
            st.caption("감지된 구체 수단: " + " · ".join(analysis["tactics"]))
        st.caption(f"예방: {analysis['watch']}")
        st.divider()

    remaining = len(news_list) - st.session_state.display_count
    if remaining > 0:
        add_count = min(10, remaining)
        if st.button(f"🔽 수법 기사 더보기 ({add_count}개 추가)", key="more_method"):
            st.session_state.display_count += 10
            st.rerun()
    else:
        st.caption(f"수법 중심 기사 {len(news_list)}건을 모두 표시했습니다.")
else:
    st.info("수법·사건 조건에 맞는 뉴스 기사가 없습니다.")

st.divider()

# ---------------------------------------------------------------------------
# 파트 2: 피싱 사기 전체 스크랩
# ---------------------------------------------------------------------------
st.subheader("최신 금융사기 Moa Moa")
st.caption(
    "투자사기·대출사기·가상자산 사기 등 "
    "다양한 금융·피싱 사기 기사를 **최신순**으로 모았습니다."
)

if all_news_list:
    current_all = all_news_list[: st.session_state.display_count_all]

    for idx, news in enumerate(current_all, 1):
        kw_label = (
            " · ".join(news["keywords"]) if news["keywords"] else news["analysis"]["primary"]
        )
        st.markdown(f"**{idx}. [{news['title']}]({news['link']})**")
        st.caption(
            f"📢 {news['press']} | 🗓️ {news['date']} | 🏷️ {kw_label}"
        )
        if news.get("description"):
            snippet = news["description"]
            st.write(snippet[:160] + ("…" if len(snippet) > 160 else ""))
        st.write("")

    remaining_all = len(all_news_list) - st.session_state.display_count_all
    if remaining_all > 0:
        add_count = min(5, remaining_all)
        if st.button(f"🔽 전체 기사 더보기 ({add_count}개 추가)", key="more_all"):
            st.session_state.display_count_all += 5
            st.rerun()
    else:
        st.caption(f"전체 스크랩 {len(all_news_list)}건을 모두 표시했습니다.")
else:
    st.info("피싱 사기 관련 전체 스크랩 기사가 없습니다.")

st.caption(
    "본 서비스는 공개 뉴스 키워드·요약문 분석 기반 예방 안내용이며, "
    "수사기관 공식 경보를 대체하지 않습니다. 의심 시 112로 신고하세요."
)
