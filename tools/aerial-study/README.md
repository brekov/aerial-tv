# Aerial Study Guard — NAS service

A small LAN service that backs the **Study Guard** feature of the Aerial Android TV app
(`app.orchard.tv`). It runs on a NAS in Docker, stores everything locally, and exposes:

- a **5-question quiz** API (word → image questions today, generic types for the future),
- **speech-to-text** for short TV voice recordings with `faster-whisper` (CPU, int8),
- an **admin page** to upload images, write drafts, activate questions and trigger
  AI draft generation (DeepSeek / Xiaomi MiMo, OpenAI-compatible),
- Local **SQLite** storage for materials, questions, revisions, generation jobs,
  quiz sessions and attempts.

No public cloud is required. AI is optional: without an API key you can still upload
images and create/manage questions by hand.

---

## Architecture

```
Aerial TV (LAN)                      NAS: aerial-study container
──────────────                       ────────────────────────────
POST /api/v1/asr ───────────────────▶  faster-whisper (lazy, queue=1, CPU int8)
POST /api/v1/sessions ──────────────▶  pick 5 active questions (random, no repeats)
POST /api/v1/sessions/{id}/answer ──▶  exact match (optional AI judge) + progress
GET  /api/v1/images/{sha}?s=… ──────▶  image bytes (session-scoped capability URL)
/admin (browser) ───────────────────▶  uploads / drafts / activation / AI generation
                                             │
                                             ▼
                                      /data/study.db (SQLite WAL)
```

One container, one port (`8900`), no external services. AI providers are only called
outbound when an admin triggers generation or (optionally) AI answer judging.

### Files

```
aerial-study/
├── app/
│   ├── main.py            FastAPI app factory, error handlers, logging
│   ├── config.py          env/.env settings (secrets are repr-hidden)
│   ├── db.py              SQLite connections, schema init, settings table
│   ├── schema.sql         tables: materials, questions, question_revisions,
│   │                      generation_jobs, quiz_sessions, quiz_attempts, settings
│   ├── auth.py            TV device token + HMAC admin session cookie/bearer
│   ├── materials.py       sha256-addressed upload storage
│   ├── questions.py       question CRUD, revisions, activation rules, judging
│   ├── sessions.py        session selection, progress, wrong-answer restart
│   ├── asr.py             faster-whisper lazy loader + single-worker queue
│   ├── providers.py       DeepSeek / Xiaomi MiMo OpenAI-compatible client
│   ├── generation.py      AI generation jobs (draft-only)
│   ├── api_public.py      /api/v1 TV endpoints + /health
│   ├── api_admin.py       /api/v1/admin JSON API
│   ├── web_admin.py       /admin login + dashboard HTML
│   ├── templates/         Jinja2 templates (no CDN / no JS build)
│   └── static/            admin.css, admin.js
├── tests/                 pytest suite (AI + ASR mocked)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt       runtime (includes faster-whisper)
├── requirements-test.txt  lightweight local test deps (no faster-whisper)
├── .env.example
└── README.md
```

---

## Quick start on the NAS

Requirements: Docker + Docker Compose v2, a CPU NAS, and the TV on the same LAN.

```bash
# on the NAS, from this directory (tools/aerial-study)
cp .env.example .env
# edit .env: at minimum set STUDY_DEVICE_TOKEN and ADMIN_PASSWORD

# the host directory mounted at /data (must exist)
sudo mkdir -p /vol2/1000/study
# if you run the container as uid 1000 (default) and the directory is root-owned:
sudo chown -R 1000:1000 /vol2/1000/study

docker compose config       # validate interpolation
docker compose up -d --build
docker compose logs -f study
curl http://127.0.0.1:8900/health
```

Open `http://<NAS-IP>:8900/admin` and sign in with `ADMIN_PASSWORD`.
The TV app should use `http://<NAS-IP>:8900` and the token from `STUDY_DEVICE_TOKEN`.

> The compose file mounts **`/vol2/1000/study` → `/data`** exactly as specified.
> Change that one line if your NAS uses a different path.

The first ASR request downloads the configured whisper model (e.g. `small`, several
hundred MB) into `/data/models`. That can take longer than `ASR_TIMEOUT_SECONDS`;
the next request will be fast. See [ASR notes](#asr-notes).

---

## Configuration

All settings come from environment variables. Docker Compose reads `.env` in this
directory; `python -m uvicorn …` also loads a local `.env` via `python-dotenv`.
API keys are **only** read from the environment and are never stored in SQLite,
returned by an API, or written to logs.

| Variable | Default | Meaning |
|---|---|---|
| `DATA_DIR` | `/data` | SQLite + images + model cache root |
| `IMAGES_DIR` | `$DATA_DIR/images` | content-addressed image files |
| `MATERIALS_DIR` | `$DATA_DIR/materials` | PDF/text material (future types) |
| `DB_PATH` | `$DATA_DIR/study.db` | SQLite database |
| `STUDY_DEVICE_TOKEN` | _(empty)_ | TV shared token. Empty disables TV auth (LAN-only mode) |
| `ADMIN_PASSWORD` | _(empty)_ | admin password. Empty disables `/admin` |
| `ADMIN_SECRET_KEY` | _(derived)_ | extra HMAC key for admin cookies |
| `ADMIN_SESSION_HOURS` | `12` | admin cookie/bearer lifetime |
| `SESSION_TTL_HOURS` | `24` | quiz session lifetime |
| `QUESTIONS_PER_SESSION` | `5` | questions per quiz run |
| `IMAGE_MAX_MB` | `10` | max image upload size |
| `ASR_MODEL` | `small` | `tiny` / `base` / `small` / … faster-whisper model |
| `ASR_DEVICE` | `cpu` | keep `cpu` on a NAS |
| `ASR_COMPUTE_TYPE` | `int8` | CPU quantisation |
| `ASR_LANGUAGE` | `auto` | `auto`, `zh`, `en`, … |
| `ASR_BEAM_SIZE` | `1` | 1 is fastest for short utterances |
| `ASR_MAX_MB` | `20` | max audio upload size |
| `ASR_QUEUE_SIZE` | `8` | pending ASR requests before 429 |
| `ASR_TIMEOUT_SECONDS` | `120` | per-request wait before 504 (worker keeps going) |
| `ASR_PCM_*` | 16 kHz / mono / 16-bit | headerless PCM wrapping |
| `DEEPSEEK_API_KEY` | _(empty)_ | optional; enables DeepSeek vision generation |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible base |
| `DEEPSEEK_MODEL` | `deepseek-chat` | model id (must accept image content if used for vision) |
| `DEEPSEEK_AUTH_HEADER` | `Authorization` | header name; `Authorization` → `Bearer <key>`, others get the raw key |
| `XIAOMI_MIMO_API_KEY` / `_BASE_URL` / `_MODEL` / `_AUTH_HEADER` | _(empty)_ | same, for MiMo |
| `AI_PROVIDER` | `deepseek` | default provider |
| `AI_JUDGE_ENABLED` | `0` | optional AI fallback when exact answer matching fails |
| `AI_TIMEOUT_SECONDS` | `60` | outbound AI timeout |
| `PUBLIC_BASE_URL` | _(empty)_ | optional absolute prefix for `imageUrl` (e.g. `http://nas:8900`) |
| `PORT` | `8900` | host port mapping (container always listens on 8900) |
| `TZ` | `Asia/Shanghai` | container timezone |
| `LOG_LEVEL` | `INFO` | service log level |

Admin provider **routing** (base URL, model, auth-header name, default provider,
AI-judge toggle) can also be changed in `/admin`; those overrides live in the
`settings` table. Keys stay in `.env`.

---

## TV / public API

Base URL: `http://<NAS-IP>:8900`. All TV endpoints accept the device token as
`Authorization: Bearer <token>`, `X-Study-Token: <token>`, or (for session creation
and answers) a `token` JSON field.

### Health

```bash
curl http://nas:8900/health
```

```json
{
  "status": "ok",
  "service": "aerial-study",
  "version": "0.1.0",
  "database": "ok",
  "activeQuestions": 12,
  "asr": {"available": true, "model": "small", "loaded": false, "queued": 0},
  "ai": {"providers": {"deepseek": {"configured": false}}, "defaultProvider": "deepseek"},
  "auth": {"deviceTokenRequired": true, "adminConfigured": true}
}
```

### Create a session

Picks 5 random **active** questions (no repeats). If fewer than 5 are active the
API returns `409` with a message to activate more questions first.

```bash
curl -X POST http://nas:8900/api/v1/sessions \
  -H "X-Study-Token: $STUDY_DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"deviceId":"xiaomi-mftr0"}'
```

```json
{
  "session": {"id": "6a17…", "status": "active", "createdAt": "…", "expiresAt": "…"},
  "questions": [
    {"id": 1, "type": "word_image", "prompt": "What is this?",
     "imageUrl": "/api/v1/images/<sha256>?s=<session-id>", "lang": "en", "difficulty": 1}
  ],
  "expiresAt": "…"
}
```

Answers are **never** included in session/question payloads.

### Progress

```bash
curl -H "X-Study-Token: $STUDY_DEVICE_TOKEN" \
  http://nas:8900/api/v1/sessions/<session-id>
```

Returns the session header, `progress` (`currentIndex`, `total`, `correct`, `wrong`,
`restarts`, `finished`), and the 5 question payloads (no answers).

### Answer

Send a transcript (from the TV's own recogniser) **or** base64 audio to be
transcribed by this service. `transcript` wins when both are present.

```bash
curl -X POST http://nas:8900/api/v1/sessions/<session-id>/answer \
  -H "X-Study-Token: $STUDY_DEVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"questionId": 1, "transcript": "apple"}'
```

```json
{
  "correct": true,
  "progress": {"currentIndex": 1, "answered": 1, "total": 5, "remaining": 4,
               "correct": 1, "wrong": 0, "restarts": 0, "finished": false},
  "finished": false,
  "restart": false,
  "questionId": 1,
  "judgeMethod": "exact",
  "session": {"id": "6a17…", "status": "active", "expiresAt": "…"},
  "nextQuestion": {"id": 2, "type": "word_image", "prompt": "…", "imageUrl": "…"}
}
```

Answer semantics:

- **correct** → advance one question; after the 5th correct answer `finished: true`
  and the session status becomes `finished`.
- **wrong** → `restart: true`, `currentIndex` resets to 0, the same 5 questions are
  asked again. Attempts and restart count are recorded.
- Answers must be for the **current** question (`409` otherwise).
- Expired sessions (`SESSION_TTL_HOURS`) return `410`.
- Exact matching is case/punctuation/space-insensitive and accepts alternatives
  separated by `|` in the admin answer, e.g. `apple|apples` (Chinese punctuation is
  handled too). Optional AI judging can be enabled in `/admin`.

Audio alternative (base64 of WAV/PCM/webm):

```json
{"questionId": 1, "audio": "<base64>", "audioFormat": "audio/wav"}
```

### Speech-to-text

```bash
curl -X POST http://nas:8900/api/v1/asr \
  -H "X-Study-Token: $STUDY_DEVICE_TOKEN" \
  -F "file=@voice.wav;type=audio/wav"
```

```json
{"text": "apple", "language": "en", "audioSeconds": 1.28}
```

Accepts WAV, headerless PCM (wrapped as 16 kHz mono 16-bit by default; configure
with `ASR_PCM_*`), and containers faster-whisper can decode (webm/opus, ogg, mp3,
m4a; the image also installs `ffmpeg`). The worker queue is strictly **1**. Queue
full → `429`; request wait timeout → `504`.

### Images

`GET /api/v1/images/{sha256}?s=<session-id>` is a capability URL for TV `<img>` tags.
The device token or the admin session cookie also authorises image reads. Files are
stored by sha256 and are immutable, so responses are cacheable (`private, max-age=86400`).

### Error format

```json
{"detail": "not enough active questions: need 5, have 2; activate questions in the admin page first",
 "error": "SessionError"}
```

`401` invalid/missing token · `404` unknown session/image · `409` not enough questions /
wrong question / already finished · `410` expired session or missing image file ·
`413` upload too large · `415` unsupported material · `422` invalid input · `429` ASR
queue full · `503` ASR dependency missing / AI key missing · `504` ASR timeout.

---

## Admin page

`http://<NAS-IP>:8900/admin` (password = `ADMIN_PASSWORD`). The page talks to the
same-origin JSON API using a short-lived signed cookie; scripts can also use
`POST /admin/login` with JSON and send the returned token as a bearer.

Workflow:

1. **Upload material** — PNG/JPEG/WebP. Stored by sha256; identical uploads are
   deduplicated.
2. **Manual draft** — write a prompt/answer and attach an image. Works with no AI key.
3. **AI generation** — choose an image and provider; the job runs in the background
   and inserts **draft** questions only. Jobs and errors are listed in the page.
4. **Review / activate** — activating a `word_image` question requires prompt, answer
   and image. Statuses: `draft → reviewed → active`; `disabled` hides it from sessions.
   Every edit creates a `question_revisions` snapshot.
5. **History** — recent revisions, quiz sessions with attempt transcripts and grading.
6. **Providers** — base URL / model / auth header / default provider / AI-judge toggle;
   API key status is shown but keys are never displayed.

### Admin JSON API

All routes require the admin cookie or bearer token unless noted.

| Method & path | Purpose |
|---|---|
| `GET/POST /admin/login`, `POST /admin/logout` | password login / logout (HTML + JSON) |
| `GET /api/v1/admin/stats` | question/material/job/session counts |
| `GET /api/v1/admin/materials` | list materials (`?kind=image`) |
| `POST /api/v1/admin/materials` | multipart `file` (+ optional `title`), sha256-dedup |
| `GET /api/v1/admin/questions` | list (`status`, `type`, `lang`, `search`, `limit`, `offset`) |
| `POST /api/v1/admin/questions` | manual create (draft by default) |
| `GET /api/v1/admin/questions/{id}` | question + revision history |
| `PATCH /api/v1/admin/questions/{id}` | edit → new revision |
| `POST /api/v1/admin/questions/{id}/status` | `{status, note}` review/activate/disable |
| `GET /api/v1/admin/questions/{id}/revisions` | revision snapshots |
| `GET /api/v1/admin/history` | recent revisions across questions |
| `GET /api/v1/admin/sessions`, `/{id}` | session progress + attempts |
| `POST /api/v1/admin/generate` | `{materialId, provider?, lang, count}` → job (202) |
| `GET /api/v1/admin/jobs`, `/{id}` | generation job status/result |
| `GET /api/v1/admin/providers` | provider routing + `hasApiKey` flags |
| `PUT /api/v1/admin/providers/{name}` | set baseUrl / model / authHeader |
| `PUT /api/v1/admin/settings` | default provider, AI-judge toggle |

Login as a script (cookie jar):

```bash
curl -c cookies.txt -X POST http://nas:8900/admin/login \
  -d "password=$ADMIN_PASSWORD" -o /dev/null -w "%{http_code}\n"
curl -b cookies.txt http://nas:8900/api/v1/admin/stats
```

---

## AI providers (optional)

The client is OpenAI-compatible `POST {base_url}/chat/completions`. For generation it
sends the image as an OpenAI-style `image_url` data URI and expects a JSON array of
`{prompt, answer, explanation, difficulty}`.

```dotenv
DEEPSEEK_API_KEY=sk-…
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_AUTH_HEADER=Authorization

XIAOMI_MIMO_API_KEY=…
XIAOMI_MIMO_BASE_URL=https://<mimo-gateway>/v1
XIAOMI_MIMO_MODEL=<vision-model-id>
```

Important honesty notes:

- **Vision support depends on the provider/model you configure.** Not every DeepSeek
  chat model accepts image content; use a vision-capable model/endpoint. If the
  provider rejects the image, the generation job fails visibly with the provider's
  error (key values are redacted). Nothing is auto-activated.
- Xiaomi MiMo's endpoint/model ids are deployment-specific; set them explicitly.
- The service has been tested against a **mocked** OpenAI-compatible provider, not a
  live account. No real AI request was made in this build.
- AI is a convenience: all admin/manual flows work without any key.
- Outbound routing (base URL) is editable in the admin UI. Runtime keys come only
  from the environment; a malicious admin could point the client at another host,
  so keep `ADMIN_PASSWORD` strong and the admin port on the LAN.

---

## ASR notes (read this)

- **CPU-only, short utterances.** `faster-whisper` runs on `cpu` with `int8`
  (`ASR_DEVICE`, `ASR_COMPUTE_TYPE`). It is intended for one-word/short-phrase TV
  answers, not meeting transcription.
- **Lazy loading.** The model loads on the first request inside the worker thread.
  The first request after a restart can exceed `ASR_TIMEOUT_SECONDS` while the model
  downloads into `/data/models`; retry after the download finishes.
- **Concurrency 1.** A bounded FIFO queue (`ASR_QUEUE_SIZE`) is served by exactly one
  worker, keeping latency predictable on a NAS. A full queue returns `429`.
- **Model choice.** `base`/`small` are good NAS trade-offs; `tiny` is faster but less
  accurate; larger models need more RAM/CPU.
- **Audio.** TV-recorded webm/opus works via the bundled `ffmpeg`/PyAV. Raw PCM is
  wrapped with the configured sample rate/channels/width. Audio over
  `ASR_MAX_MB` is rejected.
- **Real ASR was not exercised** in this build (no model/audio on the build host).
  The test-suite mocks the engine. Verify on the actual NAS with a short Chinese and
  English recording.

---

## Data, backup and updates

Everything lives under the mounted `/data`:

```
/vol2/1000/study/
├── study.db            SQLite (WAL; also study.db-wal / study.db-shm while running)
├── images/<sha>.<ext>  uploaded images (immutable, content addressed)
├── materials/          PDF/text materials (future question types)
└── models/             faster-whisper model cache
```

Back up by copying the whole directory while the container is stopped (simplest), or
use SQLite's online backup for `study.db` while running. Restoring is copying the
directory back. `docker compose up -d --build` after updating the code applies the
idempotent schema automatically.

---

## Tests

The suite is fully offline and needs no AI key, whisper model or audio:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-test.txt
pytest
```

Covered: health/auth, schema + revision history, 5-question selection, correct
advance, wrong-answer restart, finish, expiry, image capability URLs, ASR validation
with a mocked engine, ASR queue/concurrency internals with a fake model, admin
upload/dedupe, question lifecycle, generation success/failure with a mocked provider,
provider routing without key leakage, and optional AI judging.

**Not covered (by design):** real provider network calls, real whisper transcription
accuracy, Docker image build (verify on the NAS), TLS/proxy setups.

Static checks:

```bash
ruff check app tests
ruff format --check app tests
```

---

## Security notes

- This is a **LAN service without TLS**. If it must leave the LAN, put it behind a
  reverse proxy/HTTPS and restrict access.
- TV access uses the shared `STUDY_DEVICE_TOKEN`; leave it empty only if you accept
  an unauthenticated device API on the LAN. Admin access is disabled when
  `ADMIN_PASSWORD` is empty.
- The admin cookie is HMAC-signed, `HttpOnly`, `SameSite=Lax`, and expires after
  `ADMIN_SESSION_HOURS`. Changing `ADMIN_PASSWORD`/`ADMIN_SECRET_KEY` invalidates
  existing cookies.
- AI keys are read from the environment only. They are not stored in SQLite, not
  returned by APIs, and provider errors are redacted before being logged/stored.
- Uploaded images, quiz transcripts and question answers live under `/data`; treat
  that directory as private data. There is no admin-login rate limiter (LAN tool),
  so use a strong password.
- Provider base URLs are admin-editable by design; a compromised admin session could
  redirect AI traffic. Keep the admin password strong and the port on the LAN.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `409 not enough active questions` | In `/admin`, activate at least `QUESTIONS_PER_SESSION` questions; word_image needs an attached image |
| Admin login says disabled | set `ADMIN_PASSWORD` in `.env`, `docker compose up -d` |
| TV API 401 | check `STUDY_DEVICE_TOKEN` and send `X-Study-Token`/Bearer |
| AI job failed `not configured` | set the provider key in `.env` and restart (keys are env-only) |
| AI job failed with provider error | check base URL/model and whether the model accepts images |
| ASR 503 `faster-whisper is not installed` | you are running outside the Docker image; use `requirements.txt` or Docker |
| ASR 504 on first request | model download/load; wait and retry, or pre-warm with one request |
| `permission denied` writing `/data` | `sudo chown -R 1000:1000 /vol2/1000/study` (matches container uid) |
| Image 401 | include `?s=<session-id>`, the device token, or the admin cookie |
| Compose warns about `PORT` | `.env` is optional for `docker compose config`; copy `.env.example` |

---

## 中文速查

```bash
cd tools/aerial-study
cp .env.example .env        # 设置 STUDY_DEVICE_TOKEN、ADMIN_PASSWORD，按需填 DEEPSEEK_API_KEY
sudo mkdir -p /vol2/1000/study
sudo chown -R 1000:1000 /vol2/1000/study
docker compose up -d --build
curl http://127.0.0.1:8900/health
```

- 管理后台：`http://<NAS-IP>:8900/admin`，密码为 `ADMIN_PASSWORD`。
- 电视端地址：`http://<NAS-IP>:8900`，Token 为 `STUDY_DEVICE_TOKEN`。
- 图片上传后按 sha256 存放；AI 生成只产生草稿，需人工审核并激活。
- 语音识别只适合电视上的**短句**，CPU int8，单队列；首次请求会下载模型。
- 数据全部在 `/vol2/1000/study`（数据库、图片、模型），备份该目录即可。
- 没有 AI Key 时，手动上传图片、创建/激活题目完全可用。
