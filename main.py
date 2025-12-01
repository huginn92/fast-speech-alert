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
GROK_API_KEY   = os.getenv("GROK_API_KEY")
YOUR_EMAIL     = os.getenv("YOUR_EMAIL")
FROM_EMAIL     = os.getenv("FROM_EMAIL")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# ───── 7 Central Banks + Live URLs (Dec 2025) ─────
BANKS = {
    "Fed":  "https://www.federalreserve.gov/live-broadcast.htm",
    "ECB":  "https://www.ecb.europa.eu/press/tvservices/webcast/en/latest.html",
    "BOE":  "https://www.bankofengland.co.uk/news/speeches",
    "RBNZ": "https://www.rbnz.govt.nz/monetary-policy/official-cash-rate-statements",
    "BOC":  "https://www.bankofcanada.ca/press/speeches/",
    "RBA":  "https://www.rba.gov.au/speeches/",
    "BOJ":  "https://www.boj.or.jp/en/announcements/press/koen_2025/index.htm",
}

# Grok client
client = AsyncOpenAI(api_key=GROK_API_KEY, base_url="https://api.x.ai/v1")

# State tracking
last_texts       = {bank: "" for bank in BANKS}
speech_end_time  = {bank: None for bank in BANKS}

async def fetch_page(url):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
        async with session.get(url) as resp:
            return await resp.text()

def extract_speech_text(html, bank):
    soup = BeautifulSoup(html, "html.parser")
    if bank in ["Fed", "ECB"]:
        div = soup.find("div", class_=lambda x: x and "transcript" in x.lower())
        if div: return div.get_text(strip=True, separator="\n")
    # BOJ and others
    content = soup.find("div", {"id": "content"}) or soup.find("div", class_=re.compile(r"main|article|speech", re.I))
    if content:
        return content.get_text(strip=True, separator="\n")
    return soup.get_text(strip=True, separator="\n")

def speech_just_ended(bank, new_text):
    if len(new_text) < 800: return False
    phrases = ["thank you", "questions", "press conference", "q&a", "moderator", "from the floor"]
    if any(p in new_text.lower()[-800:] for p in phrases):
        if speech_end_time[bank] is None:
            speech_end_time[bank] = datetime.now()
        elif (datetime.now() - speech_end_time[bank]).seconds > 40:
            return True
    else:
        speech_end_time[bank] = None
    return False

async def classify_tone(transcript):
    prompt = f"""Classify this central bank speech as exactly one of: Hawkish, Neutral, Dovish.
Return ONLY valid JSON.

Transcript:
{transcript[:28000]}

Format:
{{"tone": "Hawkish", "confidence": 0.94, "key_sentences": ["...", "..."]}}
"""
    try:
        resp = await client.chat.completions.create(
            model="grok-beta",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            response_format={"type": "json_object"}
        )
        import json
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        print("Grok error:", e)
        return {"tone": "Neutral", "confidence": 0.0, "key_sentences": []}

def send_email(bank, result, snippet):
    color = {"Hawkish": "#d32f2f", "Dovish": "#2e7d32", "Neutral": "#616161"}[result["tone"]]
    body = f"""
    <h2 style="color:{color}">⚡ {bank} Speech – {result['tone'].upper()}</h2>
    <p><strong>Confidence:</strong> {result['confidence']*100:.0f}%</p>
    <p><strong>Key sentences:</strong></p>
    <ul>{''.join(f'<li>{s}</li>' for s in result['key_sentences'][:6])}</ul>
    <p><strong>Preview:</strong><br>{snippet[:1400].replace('\n', '<br>')}...</p>
    <p><a href="{BANKS[bank]}">Full transcript →</a></p>
    <hr><small>{datetime.now():%Y-%m-%d %H:%M:%S}</small>
    """
    msg = MIMEText(body, "html")
    msg["Subject"] = f"{bank} → {result['tone'].upper()} ({result['confidence']*100:.0f}%)"
    msg["From"] = FROM_EMAIL
    msg["To"] = YOUR_EMAIL
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(FROM_EMAIL, EMAIL_PASSWORD)
            s.send_message(msg)
        print(f"Email sent → {bank}")
    except Exception as e:
        print("Email failed:", e)

# ───── Monitoring Loop ─────
async def monitor_loop():
    print(f"Monitoring 7 banks: {', '.join(BANKS.keys())}")
    while True:
        try:
            for bank, url in BANKS.items():
                html = await fetch_page(url)
                new_text = extract_speech_text(html, bank)

                if (speech_just_ended(bank, new_text) and
                    len(new_text) > len(last_texts[bank]) + 400 and
                    new_text != last_texts[bank]):

                    print(f"{bank} speech ended – analyzing...")
                    result = await classify_tone(new_text)
                    send_email(bank, result, new_text)
                    last_texts[bank] = ""

                last_texts[bank] = new_text
            await asyncio.sleep(8)
        except Exception as e:
            print("Loop error:", e)
            await asyncio.sleep(15)

# ───── Web Server (keeps Render alive) ─────
async def health(request):
    return web.Response(text="Central Bank Multi-Monitor: 7 banks active (incl. BOJ) 🚀\n")

async def start_web():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 10000)
    await site.start()
    print("Web server OK")

async def main():
    await start_web()
    asyncio.create_task(monitor_loop())
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
