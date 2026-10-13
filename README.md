# 🚗 주말 드라이브 코스 추천 봇

매주 **금요일 19:00 KST**에 대전 유성구에서 출발하는 주말 드라이브 코스를 디스코드로 보내줍니다.

- **기본 추천**: 편도 1~2시간 코스 (관광지 → 점심 → 카페 동선, 네이버 지도 링크 포함)
- **추가 추천**: 거리 상관없는 장거리/1박 코스
- **데이터**: 한국관광공사 TourAPI(실제 장소) · Open-Meteo(주말 날씨) · Gemini(코스 구성)
- 비 예보 시 실내 위주 코스로 자동 전환, 셀토스 1.6 HEV 기준 왕복 유류비 계산
- 목적지는 주차별로 순환되어 한 바퀴 돌기 전까지 겹치지 않음

## 실행
```bash
python main.py --dry-run          # 콘솔 미리보기
python main.py --week-offset 1    # 다음 주 목적지 미리보기
python main.py                    # 디스코드 발송
```

## 환경 변수 (GitHub Secrets)
| 이름 | 설명 |
| --- | --- |
| `DISCORD_WEBHOOK_URL` | 디스코드 웹훅 |
| `GEMINI_API_KEY` | Gemini API 키 |
| `TOUR_API_KEY` | 공공데이터포털 `한국관광공사_국문 관광정보 서비스_GW` 인증키 (없으면 Gemini 단독 모드) |
| `HEV_KM_PER_L` / `GAS_PRICE_KRW` | (선택) 연비·유가 가정값, 기본 18km/L · 1,700원 |
