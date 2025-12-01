import asyncio
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
import aiohttp
from bs4 import BeautifulSoup
from openai import AsyncOpenAI
from aiohttp import web

# ───── Config (from Render environment variables) ─────
GROK_API_KEY = os.getenv("GROK_API_KEY")
YOUR_EMAIL   = os.getenv("YOUR_EMAIL")
FROM_EMAIL   = os.getenv("FROM_EMAIL")        # your Gmail
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")  # 16-char Gmail app password

# ───── Central Banks & Live Transcript URLs (2025) ─────
BANKS = {
    "Fed":     "https://www.federalreserve.gov/live-broadcast.htm",
    "ECB":     "https://www.ecb.europa.eu/press/tvservices/webcast/en/latest.html",
    "BOE":     "https://www.bankofengland.co.uk/news/speeches",
    "RBNZ":    "https://www.rbnz.govt.nz/monetary-policy/official-cash-rate-statements",
    "BOC":     "https://www.bankofcanada.ca/press/speeches/",
    "RBA":     "https://www.rba.gov.au/speeches/",
}

# Grok client (OpenAI-compatible)
client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

# Track last seen text for each bank
last_texts = {bank: "" for bank in BANKS}
speech_end_time = {bank: None for bank in BANKS}

async def fetch_page(url):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.get(url) as resp:
            return await resp.text()

def extract_speech_text(html, bank):
    soup = BeautifulSoup(html, "html.parser")
    # Fed & ECB have dedicated transcript div
    if bank in ["Fed", "ECB"]:
        div = soup.find("div", class_=lambda x: x and "transcript" in x.lower())
        if div: return div.get_text(strip=True, separator="\n")
    # Others: grab main content
    text = soup.find("div", {"class": ["content", "article", "speech"]})
    if not text:
        text = soup.body or soup
    return text.get_text(strip=True, separator="\n")

def speech_just_ended(bank, new_text):
    if len(new_text) < 800:
        return False
    end_phrases = ["thank you", "questions", "press conference", "i am happy to take", "q&a", "moderator"]
    if any(phrase in new_text.lower()[-600:] for phrase in end_phrases):
        if speech_end_time[bank] is None:
            speech_end_time[bank] = datetime.now()
        elif (datetime.now() - speech_end_time[bank]).seconds > 35:
            return True
    else:
        speech_end_time[bank] = None
    return False

async def classify_tone(transcript):
    prompt = f"""You are a senior central bank economist.
Classify this speech tone as exactly one of: Hawkish, Neutral, or Dovish.
Return ONLY valid JSON.

Transcript:
{transcript[:28000]}

Response format:
{{"tone": "Hawkish", "confidence": 0.94, "key_sentences": ["sentence 1", "sentence 2"]}}
"""
    try:
        resp = await client.chat.completions.create(
            model="grok-beta",   # or "grok-4" if you have access
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )
        import json
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"Grok error: {e}")
        return {"tone": "Neutral", "confidence": 0.0, "key_sentences": []}

def send_email(bank, result, snippet):
    color = {"Hawkish": "#d32f2f", "Dovish": "#2e7d32", "Neutral": "#616161"}.get(result["tone"], "#616161")
    body = f"""
    <h2 style="color:{color}">⚡ {bank} Speech Ended – {result['tone'].upper()}</h2>
    <p><strong>Confidence:</strong> {result['confidence']*100:.0f}%</p>
    <p><strong>Key sentences:</strong></p>
    <ul>
    {''.join(f'<li>{s}</li>' for s in result['key_sentences'][:6])}
    </ul>
    <p><strong>Preview:</strong><br>{snippet[:1400].replace(chr(10), '<br>')}...</p>
    <p><a href="{BANKS[bank]}">→ Full transcript</a></p>
    <hr><small>Sent {datetime.now():%Y-%m-%d %H:%M:%S}</small>
    """
    msg = MIMEText(body, "html")
    msg["Subject"] = f"{bank} → {result['tone'].upper()} ({result['confidence']*100:.0f}%)"
    msg["From"] = FROM_EMAIL
    msg["To"] = YOUR_EMAIL

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(FROM_EMAIL, EMAIL_PASSWORD)
            server.send_message(msg)
        print(f"Email sent for {bank}")
    except Exception as e:
        print(f"Email failed ({bank}): {e}")

# ───── Background Monitoring Loop ─────
async def monitor_loop():
    print(f"Monitoring 6 central banks: {', '.join(BANKS.keys())}")
    while True:
        try:
            for bank, url in BANKS.items():
                html = await fetch_page(url)
                new_text = extract_speech_text(html, bank)

                if (speech_just_ended(bank, new_text) and
                    len(new_text) > len(last_texts[bank]) + 400 and
                    new_text != last_texts[bank]):

                    print(f"{bank} speech detected – analyzing...")
                    result = await classify_tone(new_text)
                    send_email(bank, result, new_text)
                    last_texts[bank] = ""  # reset after alert

                last_texts[bank] = new_text

            await asyncio.sleep(7)
        except Exception as e:
            print("Loop error:", e)
            await asyncio.sleep(15)

# ───── Tiny Web Server (keeps Render alive) ─────
async def health_check(request):
    return web.Response(text="Central Bank Multi-Monitor: All 6 banks active 🚀\n")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()
    print("Web server running – Render health checks passed")

async def main():
    await start_web_server()
    asyncio.create_task(monitor_loop())
    await asyncio.Event().wait()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
    
