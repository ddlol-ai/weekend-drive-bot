"""Gemini 기반 드라이브 코스 플래너 (TourAPI 실데이터 안에서만 장소 선택)"""

from dataclasses import dataclass, field
from datetime import date
import json
import os
import time
import urllib.request
from typing import Dict, List, Optional

from modules.collectors import Spot, TripInfo

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent"
MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]


@dataclass
class CourseStep:
    time: str
    place: str
    desc: str
    addr: str = ""


@dataclass
class CoursePlan:
    title: str
    catchphrase: str
    steps: List[CourseStep] = field(default_factory=list)
    drive_tip: str = ""
    date_tip: str = ""
    solo_tip: str = ""
    parking_tip: str = ""
    season_point: str = ""
    image: str = ""


def _season(today: date) -> str:
    m = today.month
    return {12: "겨울", 1: "겨울", 2: "겨울", 3: "봄", 4: "봄", 5: "봄",
            6: "여름", 7: "여름", 8: "여름"}.get(m, "가을")


def _call_gemini(prompt: str) -> Optional[Dict]:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8, "responseMimeType": "application/json"},
    }
    # 메인 모델이 과부하(503/타임아웃)일 때 경량 모델로 자동 전환
    for model in MODELS:
        url = API_URL.replace("gemini-flash-latest", model)
        for attempt in range(1, 3):
            try:
                req = urllib.request.Request(
                    f"{url}?key={key}",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json; charset=utf-8"},
                )
                with urllib.request.urlopen(req, timeout=45) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
            except Exception as e:
                print(f"[Gemini 오류 {model} (시도 {attempt}/2)] {e}")
                time.sleep(attempt * 3)
    return None


def _spot_lines(spots: List[Spot]) -> str:
    return "\n".join(f"- [{s.sid}] ({s.kind}) {s.name} | {s.addr}" for s in spots)


def _weather_line(trip: TripInfo) -> str:
    if not trip.weather:
        return "예보 없음"
    return ", ".join(f"{w.label} {w.summary} {w.t_min}~{w.t_max}°C 강수 {w.rain_prob}%" for w in trip.weather)


def plan_main_course(trip: TripInfo, today: date) -> CoursePlan:
    d = trip.dest
    by_id = {s.sid: s for s in trip.spots}
    if trip.tour_api_ok:
        place_rule = (
            "아래 [실제 장소 목록]에 있는 장소만 사용하고, 각 단계의 place_id에 반드시 대괄호 안의 ID를 그대로 넣으세요. "
            "목록에 없는 장소는 절대 만들어내지 마세요.\n[실제 장소 목록]\n" + _spot_lines(trip.spots)
        )
    else:
        place_rule = (
            "실제 장소 데이터가 없습니다. 누구나 아는 대표 명소만 사용하고, 특정 개인 카페/식당 상호는 쓰지 말고 "
            "'○○ 인근 오션뷰 카페'처럼 일반적으로 표현하세요. place_id는 빈 문자열로 두세요."
        )
    rain = "주말 내내 비 예보이므로 실내(박물관·카페·시장) 위주로 짜고 우천 팁을 넣으세요." if trip.rainy_weekend else ""

    prompt = f"""
당신은 드라이브 여행 큐레이터입니다. 대전 유성구에 사는 차주가 이번 주말 새 차(2026 기아 셀토스 1.6 하이브리드,
HUD·서라운드뷰·원격 스마트 주차 보조·빌트인캠2 장착)로 혼자 또는 연인과 당일치기 드라이브를 갑니다.

[목적지] {d.name} ({d.region}) — 컨셉: {d.theme}
[이동] 유성 출발 편도 약 {trip.road_km}km, 약 {trip.drive_min}분
[계절] {_season(today)} ({today.month}월)
[주말 날씨] {_weather_line(trip)}
{rain}

{place_rule}

[작성 규칙] 한국어, 간결하게. 아래 JSON 형식으로만 응답:
{{
  "title": "코스 이름 (예: 서해 낙조 따라 안면도 한 바퀴)",
  "catchphrase": "설레게 만드는 한 문장",
  "steps": [
    {{"time": "09:00", "place_id": "", "place": "유성 출발", "desc": "추천 경로/고속도로 한 줄"}},
    {{"time": "10:30", "place_id": "ID", "place": "장소명", "desc": "왜 좋은지, 뭘 하면 좋은지 1문장"}}
  ],
  "drive_tip": "경치 좋은 구간·휴게소 별미 등 드라이브 팁 1~2문장",
  "date_tip": "연인과 갈 때 포인트 1문장",
  "solo_tip": "혼자 갈 때 포인트 1문장",
  "parking_tip": "주차 난이도와 서라운드뷰/원격주차 활용 팁 1문장",
  "season_point": "지금 시기에만 볼 수 있는 포인트 1문장"
}}
steps는 출발 포함 5~6단계(관광지 2~3곳 + 점심 맛집 1곳 + 카페 1곳 권장), 마지막은 귀가 출발 시간으로 마무리.
"""
    res = _call_gemini(prompt)
    if not res:
        return _fallback(trip)

    steps: List[CourseStep] = []
    image = ""
    for st in res.get("steps", []):
        pid = str(st.get("place_id") or "").strip()
        spot = by_id.get(pid)
        if trip.tour_api_ok and pid and not spot:
            continue  # 목록에 없는 ID → 환각 방지를 위해 제외
        steps.append(CourseStep(
            time=st.get("time", ""),
            place=spot.name if spot else st.get("place", ""),
            desc=st.get("desc", ""),
            addr=spot.addr if spot else "",
        ))
        if spot and spot.image and not image and spot.kind in ("관광지", "실내"):
            image = spot.image
    if not image:
        image = next((s.image for s in trip.spots if s.image), "")

    return CoursePlan(
        title=res.get("title", d.name),
        catchphrase=res.get("catchphrase", ""),
        steps=steps,
        drive_tip=res.get("drive_tip", ""),
        date_tip=res.get("date_tip", ""),
        solo_tip=res.get("solo_tip", ""),
        parking_tip=res.get("parking_tip", ""),
        season_point=res.get("season_point", ""),
        image=image,
    )


def plan_bonus(trip: TripInfo, today: date) -> CoursePlan:
    d = trip.dest
    prompt = f"""
대전 유성구에서 출발해 1박 또는 큰맘 먹은 당일치기로 갈 만한 장거리 드라이브를 짧게 소개하세요.
[목적지] {d.name} ({d.region}) — {d.theme}
[이동] 편도 약 {trip.road_km}km / 약 {trip.drive_min // 60}시간 {trip.drive_min % 60}분
[계절] {_season(today)} ({today.month}월), [주말 날씨] {_weather_line(trip)}
누구나 아는 대표 명소만 언급하고 개인 상호명은 쓰지 마세요. JSON으로만 응답:
{{"title": "코스 이름", "catchphrase": "한 문장", "drive_tip": "꼭 들를 곳 2~3개와 이유 2문장", "season_point": "지금 가면 좋은 이유 1문장"}}
"""
    res = _call_gemini(prompt) or {}
    return CoursePlan(
        title=res.get("title", d.name),
        catchphrase=res.get("catchphrase", d.theme),
        drive_tip=res.get("drive_tip", ""),
        season_point=res.get("season_point", ""),
    )


def _fallback(trip: TripInfo) -> CoursePlan:
    d = trip.dest
    steps = [CourseStep("09:00", "유성 출발", f"편도 약 {trip.drive_min}분 드라이브")]
    picks = trip.spots_of("관광지")[:2] + trip.spots_of("맛집")[:1] + trip.spots_of("카페")[:1]
    for i, s in enumerate(picks):
        steps.append(CourseStep(["10:30", "12:00", "13:00", "15:00"][i], s.name, s.kind, s.addr))
    return CoursePlan(
        title=d.name, catchphrase=d.theme, steps=steps,
        image=next((s.image for s in trip.spots if s.image), ""),
    )
