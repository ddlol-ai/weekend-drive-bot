"""디스코드 웹훅 Embed 카드 빌더"""

from datetime import datetime, timezone
import json
import os
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from modules.collectors import TripInfo
from modules.planner import CoursePlan

BOT_NAME = "주말 드라이브 큐레이터"
AVATAR = "https://img.icons8.com/color/512/car--v1.png"


def _cut(text: str, n: int) -> str:
    text = text or ""
    return text if len(text) <= n else text[: n - 1] + "…"


def _map_link(name: str, addr: str = "") -> str:
    q = f"{name} {addr.split(' ')[1] if len(addr.split(' ')) > 1 else ''}".strip()
    return f"https://map.naver.com/p/search/{urllib.parse.quote(q)}"


def _weather_text(trip: TripInfo) -> str:
    if not trip.weather:
        return "예보 정보 없음"
    return "\n".join(f"**{w.label}** {w.summary} {w.t_min}~{w.t_max}°C · ☔ {w.rain_prob}%" for w in trip.weather)


def _hm(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h else f"{m}분"


def build_main_embed(trip: TripInfo, plan: CoursePlan) -> Dict:
    lines = []
    for st in plan.steps:
        place = f"[{st.place}]({_map_link(st.place, st.addr)})" if st.addr else f"**{st.place}**"
        lines.append(f"`{st.time}` {place}\n└ {st.desc}")
    course = _cut("\n".join(lines), 1024) or "코스 정보를 불러오지 못했습니다."

    fields = [
        {"name": "🗺️ 추천 코스", "value": course, "inline": False},
        {"name": "☀️ 주말 날씨", "value": _weather_text(trip), "inline": True},
        {"name": "🔋 셀토스 HEV 예상 비용",
         "value": f"편도 약 **{trip.road_km}km** · {_hm(trip.drive_min)}\n왕복 유류비 약 **{trip.fuel_cost_round:,}원**",
         "inline": True},
    ]
    if plan.drive_tip:
        fields.append({"name": "🛣️ 드라이브 팁", "value": _cut(plan.drive_tip, 1024), "inline": False})
    who = "\n".join(x for x in (
        f"💑 **연인과**: {plan.date_tip}" if plan.date_tip else "",
        f"🎧 **혼자서**: {plan.solo_tip}" if plan.solo_tip else "",
    ) if x)
    if who:
        fields.append({"name": "👥 누구랑 가요?", "value": _cut(who, 1024), "inline": False})
    if plan.parking_tip:
        fields.append({"name": "🅿️ 주차 팁", "value": _cut(plan.parking_tip, 1024), "inline": False})
    if plan.season_point:
        fields.append({"name": "🍂 지금이 딱인 이유", "value": _cut(plan.season_point, 1024), "inline": False})

    source = "한국관광공사 TourAPI · Open-Meteo · Gemini" if trip.tour_api_ok \
        else "⚠️ 관광공사 데이터 미연동 (Gemini 추천) · 방문 전 영업 여부 확인"
    rain_badge = " ☔ 우천 대비 실내 코스" if trip.rainy_weekend else ""

    embed = {
        "title": _cut(f"🚗 이번 주말 드라이브: {plan.title}", 256),
        "description": _cut(f"**{plan.catchphrase}**\n📍 {trip.dest.region} · 대전 유성 출발{rain_badge}", 4096),
        "color": 0x2ECC71 if not trip.rainy_weekend else 0x5865F2,
        "fields": fields,
        "footer": {"text": f"기본 추천 (편도 1~2시간) · {source}"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if plan.image:
        embed["image"] = {"url": plan.image}
    return embed


def build_bonus_embed(trip: TripInfo, plan: CoursePlan) -> Dict:
    desc = f"**{plan.catchphrase}**\n📍 {trip.dest.region} · 편도 약 {trip.road_km}km ({_hm(trip.drive_min)})"
    fields = []
    if plan.drive_tip:
        fields.append({"name": "📌 꼭 들를 곳", "value": _cut(plan.drive_tip, 1024), "inline": False})
    if plan.season_point:
        fields.append({"name": "✨ 지금 가면 좋은 이유", "value": _cut(plan.season_point, 1024), "inline": False})
    fields.append({"name": "☀️ 주말 날씨", "value": _weather_text(trip), "inline": True})
    fields.append({"name": "🔋 왕복 유류비", "value": f"약 **{trip.fuel_cost_round:,}원**", "inline": True})
    return {
        "title": _cut(f"🌊 큰맘 먹고 떠나는 장거리 코스: {plan.title}", 256),
        "description": _cut(desc, 4096),
        "color": 0xE67E22,
        "fields": fields,
        "footer": {"text": "추가 추천 (거리 무관) · 1박 여행으로도 추천"},
    }


class DiscordNotifier:
    def __init__(self, webhook_url: Optional[str] = None):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL")

    def send(self, embeds: List[Dict], dry_run: bool = False) -> bool:
        payload = {"username": BOT_NAME, "avatar_url": AVATAR, "embeds": embeds}
        if dry_run:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return True
        if not self.webhook_url:
            print("❌ DISCORD_WEBHOOK_URL이 설정되지 않았습니다.")
            return False
        try:
            req = urllib.request.Request(
                self.webhook_url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "Mozilla/5.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status in (200, 204)
        except urllib.error.HTTPError as e:
            print(f"[디스코드 발송 실패] {e.code} {e.read().decode('utf-8', 'ignore')}")
        except Exception as e:
            print(f"[디스코드 발송 실패] {e}")
        return False
