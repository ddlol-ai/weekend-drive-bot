"""한국관광공사 TourAPI(KorService2) + Open-Meteo 날씨 + 거리/유류비 계산"""

from dataclasses import dataclass, field
from datetime import date, timedelta
import json
import math
import os
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from modules.destinations import ORIGIN_LAT, ORIGIN_LON, Destination

UA = {"User-Agent": "Mozilla/5.0 (WeekendDriveBot)"}
TOUR_BASE = "https://apis.data.go.kr/B551011/KorService2/locationBasedList2"

# TourAPI 콘텐츠 타입
CT_ATTRACTION = "12"
CT_CULTURE = "14"   # 박물관/미술관 등 실내 (우천 대비)
CT_FOOD = "39"      # 음식점 (카페 포함)
CAFE_CAT3 = "A05020900"  # 카페/전통찻집


@dataclass
class Spot:
    sid: str
    name: str
    addr: str
    kind: str          # 관광지 / 실내 / 맛집 / 카페
    image: str = ""
    dist_m: float = 0.0


@dataclass
class DayWeather:
    label: str         # "토 (10/17)"
    summary: str       # "☀️ 맑음"
    t_min: float
    t_max: float
    rain_prob: int

    @property
    def is_rainy(self) -> bool:
        return self.rain_prob >= 60


@dataclass
class TripInfo:
    dest: Destination
    road_km: float
    drive_min: int
    fuel_cost_round: int
    spots: List[Spot] = field(default_factory=list)
    weather: List[DayWeather] = field(default_factory=list)
    tour_api_ok: bool = False

    @property
    def rainy_weekend(self) -> bool:
        return bool(self.weather) and all(w.is_rainy for w in self.weather)

    def spots_of(self, kind: str) -> List[Spot]:
        return [s for s in self.spots if s.kind == kind]


# ---------------------------------------------------------------- 거리/유류비
def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def estimate_trip(dest: Destination) -> TripInfo:
    straight = _haversine_km(ORIGIN_LAT, ORIGIN_LON, dest.lat, dest.lon)
    road_km = straight * 1.3                       # 직선거리 → 도로거리 보정
    drive_min = int(road_km / 75 * 60) + 10        # 평균 75km/h + 시내 진출입
    km_per_l = float(os.getenv("HEV_KM_PER_L", "18"))       # 셀토스 1.6 HEV 실연비 가정
    gas_price = float(os.getenv("GAS_PRICE_KRW", "1700"))   # 휘발유 리터당 가격 가정
    fuel = int(round(road_km * 2 / km_per_l * gas_price, -2))
    return TripInfo(dest=dest, road_km=round(road_km), drive_min=drive_min, fuel_cost_round=fuel)


# ---------------------------------------------------------------- TourAPI
def _service_key() -> str:
    key = (os.getenv("TOUR_API_KEY") or "").strip()
    if not key:
        return ""
    # Encoding 키(이미 %가 포함)는 그대로, Decoding 키는 URL 인코딩
    return key if "%" in key else urllib.parse.quote(key, safe="")


def _tour_query(dest: Destination, content_type: str, rows: int = 25) -> List[Dict]:
    key = _service_key()
    params = urllib.parse.urlencode({
        "numOfRows": rows,
        "pageNo": 1,
        "MobileOS": "ETC",
        "MobileApp": "WeekendDriveBot",
        "_type": "json",
        "arrange": "S",            # 거리순 + 대표이미지 있는 것
        "mapX": dest.lon,
        "mapY": dest.lat,
        "radius": 15000,
        "contentTypeId": content_type,
    })
    url = f"{TOUR_BASE}?serviceKey={key}&{params}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8")
    data = json.loads(raw)  # 키 오류 시 XML이 오므로 여기서 예외 발생
    body = data.get("response", {}).get("body", {})
    items = body.get("items") or {}
    items = items.get("item", []) if isinstance(items, dict) else []
    return items if isinstance(items, list) else [items]


def _to_spot(it: Dict, kind: str) -> Spot:
    return Spot(
        sid=str(it.get("contentid", "")),
        name=(it.get("title") or "").strip(),
        addr=(it.get("addr1") or "").strip(),
        kind=kind,
        image=it.get("firstimage") or it.get("firstimage2") or "",
        dist_m=float(it.get("dist") or 0),
    )


def fetch_spots(dest: Destination) -> List[Spot]:
    spots: List[Spot] = []
    for ct, kind, limit in ((CT_ATTRACTION, "관광지", 10), (CT_CULTURE, "실내", 5)):
        try:
            spots += [_to_spot(it, kind) for it in _tour_query(dest, ct)[:limit]]
        except Exception as e:
            print(f"[TourAPI 경고] {dest.name} type={ct}: {e}")
            if not spots:
                raise
    try:
        food = _tour_query(dest, CT_FOOD, rows=40)
        cafes = [it for it in food if it.get("cat3") == CAFE_CAT3 or "카페" in (it.get("title") or "")]
        meals = [it for it in food if it not in cafes]
        spots += [_to_spot(it, "카페") for it in cafes[:6]]
        spots += [_to_spot(it, "맛집") for it in meals[:8]]
    except Exception as e:
        print(f"[TourAPI 경고] {dest.name} 음식점: {e}")
    # 이름 중복 제거
    seen, uniq = set(), []
    for s in spots:
        if s.name and s.name not in seen:
            seen.add(s.name)
            uniq.append(s)
    return uniq


# ---------------------------------------------------------------- 날씨 (Open-Meteo, 키 불필요)
WMO = {
    0: "☀️ 맑음", 1: "🌤️ 대체로 맑음", 2: "⛅ 구름 조금", 3: "☁️ 흐림",
    45: "🌫️ 안개", 48: "🌫️ 안개", 51: "🌦️ 이슬비", 53: "🌦️ 이슬비", 55: "🌦️ 이슬비",
    61: "🌧️ 비", 63: "🌧️ 비", 65: "🌧️ 강한 비", 71: "🌨️ 눈", 73: "🌨️ 눈", 75: "❄️ 많은 눈",
    80: "🌦️ 소나기", 81: "🌧️ 소나기", 82: "⛈️ 강한 소나기", 95: "⛈️ 뇌우", 96: "⛈️ 뇌우", 99: "⛈️ 뇌우",
}


def upcoming_weekend(today: date) -> List[date]:
    sat = today + timedelta(days=(5 - today.weekday()) % 7)
    return [sat, sat + timedelta(days=1)]


def fetch_weather(dest: Destination, today: date) -> List[DayWeather]:
    days = upcoming_weekend(today)
    params = urllib.parse.urlencode({
        "latitude": dest.lat, "longitude": dest.lon,
        "daily": "weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "Asia/Seoul",
        "start_date": days[0].isoformat(), "end_date": days[1].isoformat(),
    })
    try:
        req = urllib.request.Request(f"https://api.open-meteo.com/v1/forecast?{params}", headers=UA)
        with urllib.request.urlopen(req, timeout=12) as resp:
            d = json.loads(resp.read().decode("utf-8"))["daily"]
        out = []
        for i, day in enumerate(days):
            out.append(DayWeather(
                label=f"{'토일'[i]} ({day.month}/{day.day})",
                summary=WMO.get(int(d["weathercode"][i] or 0), "🌥️ 변덕"),
                t_min=round(d["temperature_2m_min"][i]), t_max=round(d["temperature_2m_max"][i]),
                rain_prob=int(d["precipitation_probability_max"][i] or 0),
            ))
        return out
    except Exception as e:
        print(f"[날씨 경고] {dest.name}: {e}")
        return []


def build_trip(dest: Destination, today: date, with_spots: bool = True) -> TripInfo:
    trip = estimate_trip(dest)
    trip.weather = fetch_weather(dest, today)
    if with_spots and _service_key():
        try:
            trip.spots = fetch_spots(dest)
            trip.tour_api_ok = bool(trip.spots)
        except Exception as e:
            print(f"[TourAPI 실패 → Gemini 단독 모드] {e}")
    return trip
