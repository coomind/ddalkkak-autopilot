# ddalkkak-autopilot

@ai.ddalkkak 인스타그램 자동 운영 파이프라인.

- `pipeline/render.py` — spec.json → 캐러셀 PNG(1080×1350) + 릴스 MP4(1080×1920, TTS)
- `pipeline/ig.py` — Instagram Graph API 게시·성과 수집 (토큰은 `secrets/`에 AES-256 암호화)
- `RUNBOOK.md` — 매일/매주 운영 규칙
- `posts/` — 게시물별 spec과 결과물 (jsDelivr로 공개 URL 제공)
- `state/` — 게시 로그, 성과 지표, 주제 백로그
