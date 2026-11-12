# Aerial Study Guard — NAS service

Aerial's optional repeat-learning service. The Android TV records one short WAV
per card; the NAS scores that audio directly with MiMo and returns a score.
There is deliberately **no ASR and no text judge** in this flow.

## What the TV does

A round has exactly **3 image cards**:

1. Full-screen transition, spoken `跟读学习` (repeat learning).
2. Show the picture, then speak the word and spell it:
   `apple, A. P. P. L. E`.
3. Start recording immediately after the spelling.
4. Upload only the WAV.
5. Show the score, then move to the next card.
6. Finish after the third card.

A low score does not restart the round. When no speech is detected the same card is
played again; the TV keeps the round on that card until a usable recording arrives.

## Architecture

```text
TV app
  AerialRecognitionService       records WAV only (no ASR)
  StudyOverlay                   transition, TTS, recording, score
  StudyClient                    repeat-learning HTTP client
        │
        ▼
NAS FastAPI :8900
  POST /api/v1/repeat-learning/sessions
  POST /api/v1/repeat-learning/sessions/{id}/attempts
        │
        ├─ repeat_sessions / repeat_attempts (SQLite)
        └─ MiMo 2.6 audio chat completion
```

There is one remote scoring call per card. The transcript (`heard`) and the
score both come from that same audio response.

The service also hosts:

- Vue admin SPA at `/admin`
- material upload / directory scan / mobile QR upload
- question bank, taxonomy, AI generation
- repeat-learning records

## Quick start

```bash
cd tools/aerial-study
cp .env.example .env
# edit .env: ADMIN_PASSWORD, STUDY_DEVICE_TOKEN, XIAOMI_MIMO_API_KEY
docker compose up -d --build
curl -s http://127.0.0.1:8900/health
```

Production path on the NAS: `/vol2/1000/aerial-study`; data is
`/vol2/1000/study`.

## Configuration

| Name | Default | Meaning |
| --- | --- | --- |
| `PORT` | `8900` | host port |
| `DATA_DIR` | `/data` | SQLite + question images |
| `STUDY_DEVICE_TOKEN` | empty | TV `X-Study-Token` |
| `ADMIN_PASSWORD` | empty | admin login |
| `ADMIN_SECRET_KEY` | random at start | admin cookie signing |
| `XIAOMI_MIMO_API_KEY` | empty | MiMo audio scoring / TTS |
| `XIAOMI_MIMO_BASE_URL` | vendor URL | OpenAI-compatible endpoint |
| `XIAOMI_MIMO_MODEL` | vendor default | audio-capable model |
| `PUBLIC_BASE_URL` | request host | absolute image/QR URLs |
| `STUDY_SCAN_ROOTS` | `/data/inbox` | allowed scan roots |

## TV API

Both endpoints require `X-Study-Token`.

### Create a round

```http
POST /api/v1/repeat-learning/sessions
Content-Type: application/json

{"deviceId":"tv"}
```

Response:

```json
{
  "session": {"id":"…","status":"active","total":3,"currentIndex":0,"totalScore":0},
  "cards": [
    {"id":11,"imageUrl":"http://nas:8900/api/v1/images/<sha>",
     "word":"apple","letters":["A","P","P","L","E"],
     "spellingText":"apple, A. P. P. L. E"}
  ]
}
```

The server picks three active `word_image` questions. Fewer than three returns
`409`.

### Submit a recording

```http
POST /api/v1/repeat-learning/sessions/{id}/attempts
Content-Type: application/json

{"cardId":11,"audio":"<base64 WAV>","audioFormat":"audio/wav"}
```

Response:

```json
{
  "score": 86,
  "verdict": "correct",
  "heard": "apple",
  "feedback": "发音很接近",
  "retry": false,
  "finished": false,
  "totalScore": 86,
  "progress": {"answered":1,"total":3,"finished":false},
  "nextCard": {"id":12,"imageUrl":"…","word":"bear","letters":["B","E","A","R"]}
}
```

- `verdict`: `correct | near | wrong | no_speech`
- `retry=true`: same card again, no score committed
- `finished=true` after card 3
- MiMo unavailable returns `503`; do not advance or write a false score

### Image

`GET /api/v1/images/{sha256}` accepts the TV token or the admin cookie.
Repeat-learning image URLs are absolute and not session-scoped.

## Admin

`/admin/login` then `/admin`.

Pages: Overview, Questions, Materials, Taxonomy, Records, Wrong book, Settings.

- Questions show image thumbnails, readable titles, labels and attempt stats.
- Materials support phone QR upload, directory scan, metadata edit and safe delete.
- Questions support preview, edit, image/options changes and soft delete.
- AI generation creates drafts only.
- Settings is informational; legacy cleanup endpoints are not exposed in the UI.

## Database

Current schema version: **4**.

Repeat-learning tables:

- `repeat_sessions`
- `repeat_attempts`

Legacy `quiz_sessions` / `quiz_attempts` remain for historical records only.
The repeat flow does not use the legacy 5-question/text-judge API.

## Tests

```bash
python3 -m pytest -q tests/test_unit.py
```

The full API suite needs `python-multipart` and is normally run inside the
Docker image. Unit tests cover utility/redaction; server API smoke tests are
done against a real Docker instance.

## Migration notes

- v2 added taxonomy, material metadata and question categories.
- v4 added repeat-learning tables.
- No destructive migration of old sessions is performed.
