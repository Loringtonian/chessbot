"""Prove the editable system-prompt box is wired into the live session.

Types a distinctive instruction into the on-page textarea, connects, and checks
the tutor's actual spoken greeting obeys it. If it does, the edited prompt is
really reaching the realtime model.
"""

import asyncio
import sys
from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8000/german"
CUSTOM = ("Du bist ein Deutschlehrer. WICHTIG: Beginne jede einzelne Antwort "
          "immer mit dem Wort PFANNKUCHEN in Grossbuchstaben, ohne Ausnahme.")


async def main() -> int:
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir="/tmp/german_promptwire_profile", channel="chrome", headless=False,
            args=["--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"])
        try:
            await ctx.grant_permissions(["microphone"], origin="http://127.0.0.1:8000")
            page = await ctx.new_page()
            await page.goto(URL)
            if not await page.evaluate("document.getElementById('login').hidden"):
                await page.fill("#username", "Judith"); await page.fill("#password", "Ottawa")
                await page.click("#loginBtn"); await page.wait_for_timeout(700)
            # wait until the default prompt has loaded into the box, then overwrite it
            await page.wait_for_function("document.getElementById('promptText').value.length > 20")
            await page.fill("#promptText", CUSTOM)
            await page.click("#connectBtn")
            for _ in range(40):
                if await page.evaluate("document.getElementById('connectBtn').classList.contains('live')"):
                    break
                await page.wait_for_timeout(500)
            # wait for the greeting turn
            for _ in range(30):
                if await page.evaluate("window.__diag.tutorTurns.length > 0"):
                    break
                await page.wait_for_timeout(500)
            turns = await page.evaluate("window.__diag.tutorTurns")
            greeting = (turns[0] if turns else "")
            print("tutor greeting:", repr(greeting[:160]))
            ok = "PFANNKUCHEN" in greeting.upper()
            print("VERDICT:", "PASS — edited prompt is wired into the live session"
                  if ok else "FAIL — custom prompt not applied")
            return 0 if ok else 1
        finally:
            await ctx.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
