"""Voice-answer transcription endpoint: the cross-device path for spoken answers
(browsers where SpeechRecognition is unavailable record audio; we transcribe it
server-side). The AI call is mocked."""

from __future__ import annotations

from app.ai import router as ai_router
from tests.conftest import requires_mongo
from tests.test_security import _auth, _login, _register

pytestmark = [requires_mongo]


async def test_transcribe_returns_text(client, monkeypatch):
    email = await _register(client)
    tokens = await _login(client, email)
    monkeypatch.setattr(ai_router, "transcribe", lambda path, model="whisper-1": "my spoken answer")

    resp = await client.post(
        "/api/v1/interviews/transcribe",
        files={"audio": ("answer.webm", b"\x00\x01\x02fakeaudio", "audio/webm")},
        headers=_auth(tokens),
    )
    assert resp.status_code == 200
    assert resp.json()["text"] == "my spoken answer"


async def test_transcribe_rejects_empty_audio(client):
    email = await _register(client)
    tokens = await _login(client, email)
    resp = await client.post(
        "/api/v1/interviews/transcribe",
        files={"audio": ("answer.webm", b"", "audio/webm")},
        headers=_auth(tokens),
    )
    assert resp.status_code == 400
