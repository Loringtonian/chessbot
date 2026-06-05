"""Lesson test: does the tutor correct per the spec?

A scripted student speaks (out loud, real acoustic input) and deliberately makes
the SAME grammar mistake twice — "ich gehen" instead of "ich gehe". Per the
prompt, the tutor should let small mistakes slide but correct a REPEATED one.
Prints the whole conversation for judgement.
"""

import asyncio
import os
import subprocess
import sys

import httpx
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8000/german"

# Student turns. The "ich gehen" error appears in L1 and again in L2 (repeat).
STUDENT = [
    ("l1", "Hallo! Ich heiße Judith. Ich gehen jeden Tag zur Uni."),
    ("l2", "Ich gehen auch am Wochenende oft in die Bibliothek."),
    ("l3", "Danke dir! Was soll ich als Nächstes üben?"),
]


def synth(key, text, path):
    if os.path.exists(path) and os.path.getsize(path) > 8000:
        return
    r = httpx.post("https://api.openai.com/v1/audio/speech",
                   headers={"Authorization": f"Bearer {key}"},
                   json={"model": "gpt-4o-mini-tts", "voice": "coral",
                         "input": text, "response_format": "wav"}, timeout=60)
    r.raise_for_status(); open(path, "wb").write(r.content)


async def say_and_wait(page, wav, timeout_ms=18000):
    before = await page.evaluate("window.__diag.tutorTurns.length")
    subprocess.run(["afplay", wav])
    waited = 0
    while waited < timeout_ms:
        if await page.evaluate("window.__diag.tutorTurns.length") > before:
            await page.wait_for_timeout(2000)  # let the reply finish
            break
        await page.wait_for_timeout(500); waited += 500


async def main() -> int:
    key = [l.split("=", 1)[1].strip() for l in open(".env") if l.startswith("OPENAI_API_KEY=")][0]
    wavs = []
    for tag, text in STUDENT:
        path = f"/tmp/lesson_{tag}.wav"; synth(key, text, path); wavs.append(path)

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir="/tmp/german_lesson_profile", channel="chrome", headless=False,
            args=["--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        try:
            await ctx.grant_permissions(["microphone"], origin="http://127.0.0.1:8000")
            page = await ctx.new_page()
            await page.goto(f"{URL}?aec=1")
            if not await page.evaluate("document.getElementById('login').hidden"):
                await page.fill("#username", "Judith"); await page.fill("#password", "Ottawa")
                await page.click("#loginBtn"); await page.wait_for_timeout(700)
            # ensure DEFAULT prompt (clear any saved override)
            await page.evaluate("localStorage.removeItem('german_prompt')")
            await page.reload()
            await page.wait_for_function("document.getElementById('promptText').value.length > 20")
            await page.click("#connectBtn")
            for _ in range(40):
                if await page.evaluate("document.getElementById('connectBtn').classList.contains('live')"):
                    break
                await page.wait_for_timeout(500)
            for _ in range(30):
                if await page.evaluate("window.__diag.tutorTurns.length > 0"):
                    break
                await page.wait_for_timeout(500)

            for wav in wavs:
                await say_and_wait(page, wav)

            diag = await page.evaluate("window.__diag")
            tutor = diag["tutorTurns"]; user = diag["userTurns"]
            print("\n" + "=" * 72)
            print("STUDENT lines spoken (scripted):")
            for _, t in STUDENT:
                print("   •", t)
            print("\nHEARD (tutor's transcription of the student):")
            for u in user:
                print("   →", u)
            print("\nTUTOR turns:")
            for i, t in enumerate(tutor):
                print(f"   [{i}] {t}")
            print("=" * 72)

            corrected = any(("gehe " in t.lower() or "ich gehe" in t.lower() or "gehst" in t.lower()
                             or "konjug" in t.lower() or "grammatik" in t.lower())
                            for t in tutor[1:])  # skip greeting
            heard_error = any("gehen" in u.lower() for u in user)
            print("student's 'ich gehen' was heard:", heard_error)
            print("tutor corrected the repeated mistake (mentions 'gehe'/conjugation):", corrected)
            return 0 if corrected else 1
        finally:
            await ctx.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
