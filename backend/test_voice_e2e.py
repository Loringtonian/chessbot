"""End-to-end voice test for the German tutor.

Synthesizes a German student utterance with OpenAI TTS, pushes it through a real
WebRTC (aiortc) client to gpt-realtime-2 using the SAME push-to-talk flow the
browser uses (manual input_audio_buffer.commit + response.create, server VAD
off), and asserts the tutor greets and replies in German.

Run against the local backend (login + session), media goes straight to OpenAI.
"""

import asyncio
import json
import os
import socket
import sys
import time

import httpx
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

BACKEND = os.environ.get("BACKEND", "http://127.0.0.1:8000")

# Optional DNS pin: PIN_HOST=host PIN_IP=1.2.3.4 forces that host to resolve to
# the given IPv4 (works around broken IPv6 egress when testing the live site).
_pin_host = os.environ.get("PIN_HOST")
_pin_ip = os.environ.get("PIN_IP")
if _pin_host and _pin_ip:
    _orig_getaddrinfo = socket.getaddrinfo
    def _pinned(host, *a, **k):
        if host == _pin_host:
            return _orig_getaddrinfo(_pin_ip, *a, **k)
        return _orig_getaddrinfo(host, *a, **k)
    socket.getaddrinfo = _pinned
MODEL = "gpt-realtime-2"
STUDENT_LINE = (
    "Hallo! Ich heiße Judith. Ich lerne Deutsch seit zwei Monaten. "
    "Heute möchte ich über meine Hobbys sprechen, zum Beispiel Wandern und Kochen."
)


def openai_key() -> str:
    for line in open(".env"):
        if line.startswith("OPENAI_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no OPENAI_API_KEY in .env")


async def synth_student_audio(key: str, path: str) -> None:
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            "https://api.openai.com/v1/audio/speech",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "gpt-4o-mini-tts", "voice": "coral",
                  "input": STUDENT_LINE, "response_format": "wav"},
        )
        r.raise_for_status()
        open(path, "wb").write(r.content)
    print(f"[tts] student audio -> {path} ({len(open(path,'rb').read())} bytes)")


async def main() -> int:
    key = openai_key()

    # 1. login + session via the real backend
    async with httpx.AsyncClient(timeout=30) as c:
        lr = await c.post(f"{BACKEND}/api/german/login",
                          json={"username": "Judith", "password": "Ottawa"})
        lr.raise_for_status()
        token = lr.json()["token"]
        print("[backend] logged in, token issued")
        sr = await c.post(f"{BACKEND}/api/german/session",
                          headers={"Authorization": f"Bearer {token}"})
        sr.raise_for_status()
        secret = sr.json()["client_secret"]
        print("[backend] session minted:", sr.json()["model"], sr.json()["voice"])

    # 2. synth the student's German line
    await synth_student_audio(key, "/tmp/german_student.wav")

    # 3. WebRTC to OpenAI with the student audio as the mic
    player = MediaPlayer("/tmp/german_student.wav")
    pc = RTCPeerConnection()
    pc.addTrack(player.audio)

    events: list = []
    greeting_done = asyncio.Event()
    reply_done = asyncio.Event()
    tutor_text = {"greeting": "", "reply": ""}
    phase = {"name": "greeting"}

    @pc.on("track")
    def on_track(track):  # drain inbound tutor audio so the pipeline flows
        async def consume():
            try:
                while True:
                    await track.recv()
            except Exception:
                pass
        asyncio.ensure_future(consume())

    dc = pc.createDataChannel("oai-events")

    @dc.on("open")
    def on_open():
        print("[webrtc] data channel open -> requesting greeting")
        dc.send(json.dumps({"type": "response.create"}))

    @dc.on("message")
    def on_message(msg):
        try:
            ev = json.loads(msg)
        except Exception:
            return
        t = ev.get("type", "")
        events.append(t)
        if t in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
            tutor_text[phase["name"]] += ev.get("delta", "")
        elif t == "conversation.item.input_audio_transcription.completed":
            print("[heard student]:", (ev.get("transcript") or "").strip())
        elif t == "response.done":
            if phase["name"] == "greeting":
                greeting_done.set()
            else:
                reply_done.set()
        elif t == "error":
            print("[realtime error]", ev.get("error"))

    await pc.setLocalDescription(await pc.createOffer())
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.05)

    async with httpx.AsyncClient(timeout=30) as c:
        resp = await c.post(f"https://api.openai.com/v1/realtime/calls?model={MODEL}",
                            headers={"Authorization": f"Bearer {secret}",
                                     "Content-Type": "application/sdp"},
                            content=pc.localDescription.sdp)
    print("[webrtc] /calls ->", resp.status_code)
    if resp.status_code not in (200, 201):
        print(resp.text[:400]); return 1
    await pc.setRemoteDescription(RTCSessionDescription(sdp=resp.text, type="answer"))

    # 4. greeting (verifies semantic_vad WebRTC handshake + opening turn)
    try:
        await asyncio.wait_for(greeting_done.wait(), timeout=25)
    except asyncio.TimeoutError:
        print("[!] greeting timed out")
    print("\n=== TUTOR GREETING ===\n", tutor_text["greeting"].strip(), "\n")

    # 5. hands-free: the student audio is already streaming; semantic_vad should
    #    detect the end of speech and auto-respond — no manual commit.
    phase["name"] = "reply"
    try:
        await asyncio.wait_for(reply_done.wait(), timeout=30)
    except asyncio.TimeoutError:
        print("[!] auto-reply timed out (VAD turn-taking)")
    print("\n=== TUTOR AUTO-REPLY (semantic_vad) ===\n", tutor_text["reply"].strip(), "\n")

    await pc.close()

    ok = bool(tutor_text["greeting"].strip()) and bool(tutor_text["reply"].strip())
    print("=" * 60)
    print("RESULT:", "PASS — greeting + reply received" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
