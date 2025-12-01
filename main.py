import asyncio
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
import aiohttp
from bs4 import BeautifulSoup
from openai import AsyncOpenAI  # Official client – works with Grok

# ───── Config (reads from Render/GitHub secrets) ─────
GROK_API_KEY = os.getenv("GROK_API_KEY")
YOUR_EMAIL = os.getenv("YOUR_EMAIL")
FROM_EMAIL = os.getenv("FROM_EMAIL")        # your Gmail
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")  # 16-char Gmail app password

URL = "https://www.federalreserve.gov/live-broadcast.htm"  # Fed live transcript

# Grok client (OpenAI-compatible)
client = AsyncOpenAI(
    api_key=GROK_API_KEY,
    base_url="https://api.x.ai/v1"
)

last_text = ""
speech_end_time = None

async def fetch_page():
    async with aiohttp.ClientSession() as session:
        async with session.get(URL, timeout=20) as resp:
            return await resp.text()

def extract_speech_text(html):
    soup = BeautifulSoup(html, "html.parser")
    # Fed live transcript is usually in <div class="col-xs-12 col-sm-12 col-md-9 col-lg-9">
    text = soup.find("div", class_="transcript")
    if text:
        return text.get_text(strip=True, separator="\n")
    # Fallback
