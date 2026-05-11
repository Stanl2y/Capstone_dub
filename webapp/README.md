# Webapp

영화 더빙 파이프라인의 웹 UI/UX. **백엔드/프론트 모두 도커 컨테이너로 실행**한다. 호스트 conda env 는 사용하지 않는다.

## 구성

| 서비스 | 컨테이너 | 호스트 포트 | 비고 |
|---|---|---|---|
| `webapp-backend` | python:3.12-slim + docker CLI + FastAPI | 8000 | 호스트 `/var/run/docker.sock` 마운트 → 기존 GPU 서비스로 `docker compose exec` |
| `webapp-frontend` | node:20-alpine + Vite dev server | 5173 | `/api`·`/static`·`/ws` 를 `webapp-backend:8000` 으로 proxy |
| `controller` / `demucs` / `speaker` / `tts-cosyvoice` | 기존 그대로 | — | 변경 없음. webapp-backend 가 docker socket 으로 호출 |

## Dev 기동

```powershell
# 처음 한 번 — 이미지 빌드
powershell -ExecutionPolicy Bypass -File .\scripts\webapp\dev.ps1 -Build

# 이후 — 두 컨테이너만 띄움 (foreground 로그 확인)
powershell -ExecutionPolicy Bypass -File .\scripts\webapp\dev.ps1
```

브라우저 — http://localhost:5173

백엔드 헬스 — http://localhost:8000/api/health (docker CLI 통신 + 4개 GPU 서비스 상태 표시)

## 디자인 시스템

`design.md` (Ollama) 패턴을 채용한다. Tailwind 토큰은 `webapp/frontend/tailwind.config.ts` 에 그대로 옮겨 두었다.
- 모든 인터랙티브 = `rounded-full` (pill).
- 카드 = `rounded-lg` + 1px hairline + 그림자 금지.
- 폰트 = Nunito(헤딩) / Inter(본문) / JetBrains Mono(코드) / Pretendard(한글 fallback).
- 단 1회 inverted dark surface — 가장 강조하고 싶은 KPI 1개에만 사용.

## 폴더

```
webapp/
  backend/
    requirements.txt
    app/
      main.py              # FastAPI 앱 + /api/health
      api/                 # Phase 1a 에서 runs/ws/uploads
      services/            # Phase 1a 에서 pipeline_runner/run_store/...
  frontend/
    package.json
    vite.config.ts
    tailwind.config.ts
    index.html
    src/
      main.tsx App.tsx index.css
      pages/               # Upload/Progress/Chunks/Compare/Metrics
      components/ui/       # Button/Card/PillInput/TerminalCard
      lib/cn.ts
docker/
  Dockerfile.webapp-backend
  Dockerfile.webapp-frontend
scripts/webapp/
  dev.ps1
```

## 다음 단계 (Phase 1)

- `webapp/backend/app/services/pipeline_runner.py` — `docker compose exec <gpu-service> python -u src/pipeline.py` subprocess + log 파서.
- `webapp/backend/app/services/step_router.py` — 단계→GPU 서비스 라우팅 (기존 `scripts/docker/run_pipeline.ps1` 의 로직 포팅).
- REST `/api/runs` / `/api/uploads` + WS `/api/ws/runs/{id}`.
- 프론트 Upload + Progress 페이지 구현.
