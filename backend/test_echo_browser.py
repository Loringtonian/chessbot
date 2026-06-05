"""Live acoustic-echo test in a real Chrome with real speakers + mic.

Runs the tutor through a long spoken monologue (counting in German) and measures
the POST-AEC microphone level while she speaks. A/B:
  - aec=0 (control): AEC off — the mic SHOULD pick up her voice from the speakers
    (high level, likely self-interruption). Proves the mic is live and echo is real.
  - aec=1 (real):    AEC on  — the mic should stay near-silent and she should
    count all the way through without interrupting herself.

If aec=1 mic level << aec=0 mic level, and the aec=1 monologue completes without
interruption, echo cancellation works (hands-free is safe).
"""

import asyncio
import os
import statistics
import sys

from playwright.async_api import async_playwright

URL = "http://127.0.0.1:8000/german"
MONOLOGUE = ("Bitte zähle jetzt langsam und deutlich auf Deutsch laut von "
             "eins bis zwanzig. Sage jede Zahl einzeln, ohne auf mich zu warten.")
RUNS = [int(x) for x in os.environ.get("RUNS", "0,1").split(",")]


async def run_once(p, aec: int) -> dict:
    ctx = await p.chromium.launch_persistent_context(
        user_data_dir=f"/tmp/german_echo_profile_{aec}",
        channel="chrome",
        headless=False,
        args=["--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required"],
    )
    try:
        await ctx.grant_permissions(["microphone"], origin="http://127.0.0.1:8000")
        page = await ctx.new_page()
        await page.goto(f"{URL}?aec={aec}")
        # Sign in only if the login form is showing (profile may persist a token).
        if not await page.evaluate("document.getElementById('login').hidden"):
            await page.fill("#username", "Judith")
            await page.fill("#password", "Ottawa")
            await page.click("#loginBtn")
            await page.wait_for_timeout(700)
        await page.wait_for_selector("#connectBtn", state="visible")
        await page.click("#connectBtn")

        # wait until connected (data channel open => meter running)
        for _ in range(40):
            st = await page.evaluate("(window.__diag && document.getElementById('connectBtn').classList.contains('live'))")
            if st:
                break
            await page.wait_for_timeout(500)

        await page.wait_for_timeout(6000)  # let the greeting play + settle
        # baseline ambient (tutor silent) samples
        ambient = []
        for _ in range(8):
            ambient.append(await page.evaluate("window.__diag.micRMS"))
            await page.wait_for_timeout(150)

        # drive the long monologue
        await page.evaluate("(t)=>window.__diag.say(t)", MONOLOGUE)
        await page.wait_for_timeout(26000)  # let her count while we sample mic

        diag = await page.evaluate("window.__diag")
        while_tutor = diag.get("micRMSWhileTutor", []) or [0]
        return {
            "aec": aec,
            "connected": True,
            "ambient_avg": round(statistics.mean(ambient or [0]), 4),
            "while_tutor_avg": round(statistics.mean(while_tutor), 4),
            "while_tutor_max": round(max(while_tutor), 4),
            "while_tutor_n": len(while_tutor),
            "speech_started_while_tutor": diag.get("speechStartedWhileTutor"),
            "responses_cancelled": diag.get("responsesCancelled"),
            "tutor_turns": diag.get("tutorTurns", []),
        }
    finally:
        await ctx.close()


def show(r):
    print(f"  aec={r['aec']}  ambient_avg={r['ambient_avg']}  "
          f"mic_while_tutor avg={r['while_tutor_avg']} max={r['while_tutor_max']} (n={r['while_tutor_n']})  "
          f"speech_started_while_tutor={r['speech_started_while_tutor']}  "
          f"responses_cancelled={r['responses_cancelled']}")
    last = (r["tutor_turns"][-1] if r["tutor_turns"] else "")[:200]
    print(f"     last tutor turn: {last!r}")


async def main() -> int:
    results = {}
    async with async_playwright() as p:
        for aec in RUNS:
            print(f">>> Run aec={aec} ({'AEC off — control' if aec == 0 else 'AEC on — real'})\n")
            results[aec] = await run_once(p, aec)

    print("\n" + "=" * 70)
    for aec in RUNS:
        show(results[aec])
    print("=" * 70)

    on = results.get(1)
    reached_end = any("zwanzig" in t.lower() for t in (on["tutor_turns"] if on else []))
    no_self_interrupt = on and on["responses_cancelled"] == 0 and on["speech_started_while_tutor"] == 0
    verdict = bool(on and no_self_interrupt and reached_end)
    print("aec=1 reached end of monologue (zwanzig):", reached_end)
    print("aec=1 no echo self-interruption:         ", bool(no_self_interrupt))
    if 0 in results:
        off = results[0]
        print("control aec=0 captured tutor (mic live): ", off["while_tutor_max"] > 0.02,
              f"(off triggers={off['speech_started_while_tutor']} vs on={on['speech_started_while_tutor'] if on else '?'})")
    print("VERDICT:", "PASS — hands-free, no echo self-interruption" if verdict else "NEEDS WORK")
    return 0 if verdict else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
