"""Confirm threshold 0.75 still hears a real (louder) human voice.

Connects hands-free (AEC on), then plays a German student utterance OUT LOUD
through the speakers (a separate process, so it is NOT part of Chrome's AEC
reference and reaches the mic like a real person talking). Verifies the tutor
transcribes it and replies — i.e. the higher threshold didn't make it deaf.
"""

import asyncio
import os
import subprocess
import sys

import httpx
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8000/german"
WAV = "/tmp/german_student.wav"
LINE = "Hallo! Ich heiße Judith. Ich wohne in Ottawa und ich lerne gern Deutsch."


def ensure_wav():
    if os.path.exists(WAV) and os.path.getsize(WAV) > 10000:
        return
    key = [l.split("=", 1)[1].strip() for l in open(".env") if l.startswith("OPENAI_API_KEY=")][0]
    r = httpx.post("https://api.openai.com/v1/audio/speech",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": "gpt-4o-mini-tts", "voice": "coral", "input": LINE, "response_format": "wav"},
                   timeout=60)
    r.raise_for_status()
    open(WAV, "wb").write(r.content)


async def main() -> int:
    ensure_wav()
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir="/tmp/german_realspeech_profile",
            channel="chrome", headless=False,
            args=["--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
        )
        try:
            await ctx.grant_permissions(["microphone"], origin="http://127.0.0.1:8000")
            page = await ctx.new_page()
            await page.goto(f"{URL}?aec=1")
            if not await page.evaluate("document.getElementById('login').hidden"):
                await page.fill("#username", "Judith"); await page.fill("#password", "Ottawa")
                await page.click("#loginBtn"); await page.wait_for_timeout(700)
            await page.wait_for_selector("#connectBtn", state="visible")
            await page.click("#connectBtn")

            for _ in range(40):
                if await page.evaluate("document.getElementById('connectBtn').classList.contains('live')"):
                    break
                await page.wait_for_timeout(500)
            await page.wait_for_timeout(7000)  # let the greeting finish

            turns_before = await page.evaluate("window.__diag.tutorTurns.length")
            print("[playing student voice out loud through the speakers]")
            subprocess.run(["afplay", WAV])         # ~6s, real acoustic input to the mic
            await page.wait_for_timeout(9000)        # let VAD fire + tutor reply

            diag = await page.evaluate("window.__diag")
            heard = [e for e in diag["events"] if e["t"] == "conversation.item.input_audio_transcription.completed"]
            turns = diag["tutorTurns"]
            print("\n" + "=" * 70)
            print("user utterances transcribed by the tutor:", len(heard))
            print("tutor turns total:", len(turns), "(before student spoke:", turns_before, ")")
            if turns:
                print("last tutor turn:", repr(turns[-1][:200]))
            replied = len(turns) > turns_before
            verdict = len(heard) >= 1 and replied
            print("VERDICT:", "PASS — real voice heard at threshold 0.75 and tutor replied"
                  if verdict else "NEEDS WORK — real voice not picked up")
            return 0 if verdict else 1
        finally:
            await ctx.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
