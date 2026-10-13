"""주말 드라이브 코스 추천 봇 - 메인 실행"""

import argparse
from datetime import date, datetime, timedelta, timezone
import os


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


_load_env()

from modules.collectors import build_trip
from modules.destinations import FAR_DESTINATIONS, NEAR_DESTINATIONS, pick_weekly
from modules.planner import plan_bonus, plan_main_course
from notifier import DiscordNotifier, build_bonus_embed, build_main_embed

KST = timezone(timedelta(hours=9))


def run(dry_run: bool = False, week_offset: int = 0) -> bool:
    today = datetime.now(KST).date() + timedelta(weeks=week_offset)
    near = pick_weekly(NEAR_DESTINATIONS, today, seed=2026)
    far = pick_weekly(FAR_DESTINATIONS, today, seed=1205)
    print(f"📅 기준일 {today} | 기본: {near.name} | 추가: {far.name}")

    main_trip = build_trip(near, today, with_spots=True)
    print(f"🏞️ TourAPI 장소 {len(main_trip.spots)}건 (연동: {main_trip.tour_api_ok}) | 우천 주말: {main_trip.rainy_weekend}")
    main_plan = plan_main_course(main_trip, today)
    print(f"✨ {main_plan.title} — {main_plan.catchphrase}")

    far_trip = build_trip(far, today, with_spots=False)
    far_plan = plan_bonus(far_trip, today)
    print(f"🌊 {far_plan.title}")

    ok = DiscordNotifier().send(
        [build_main_embed(main_trip, main_plan), build_bonus_embed(far_trip, far_plan)],
        dry_run=dry_run,
    )
    print("✅ 발송 완료" if ok else "❌ 발송 실패")
    return ok


def main():
    p = argparse.ArgumentParser(description="주말 드라이브 코스 추천 봇")
    p.add_argument("--dry-run", action="store_true", help="디스코드로 보내지 않고 콘솔에 출력")
    p.add_argument("--week-offset", type=int, default=0, help="다른 주차 목적지 미리보기용")
    args = p.parse_args()
    if not run(dry_run=args.dry_run, week_offset=args.week_offset):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
