import asyncio
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from grokapi import Grok
import aiohttp
from bs4 import BeautifulSoup
from dotenv import load_dotenv

load_dotenv()  # Loads .env vars

# Config
GROK_API_KEY = os.getenv('GROK_API_KEY')
YOUR_EMAIL = os.getenv('YOUR_EMAIL')
FROM_EMAIL = os.getenv('FROM_EMAIL')  # e.g., your Gmail
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')  # Gmail app password
URL = "https://www.federalreserve.gov/live-broadcast.htm"  # Fed; change for ECB/BOE

grok = Grok(api_key=GROK_API_KEY)

last_text = ""
speech_end_time = None

async def fetch_page():
    async with aiohttp.ClientSession() as session:
        async with session.get(URL) as response:
            return await response.text()

def extract_speech_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    # Fed selector: Adjust if needed (inspect page)
    transcript_div = soup.find('div', {'class': 'transcript'}) or soup.find('p', text=lambda t: t and 'Powell' in t if t else False)
    return transcript_div.get_text(strip=True) if transcript_div else ""

def speech_just_ended(new_text):
    global speech_end_time
    if not new_text or len(new_text) == 0:
        return False
    # Detect end: Keywords + no change for 30s (tune as needed)
    end_phrases = ["thank you", "questions", "moderator", "press conference open"]
    if any(phrase in new_text.lower() for phrase in end_phrases) and len(new_text) > len(last_text) + 200:
        if speech_end_time is None:
            speech_end_time = datetime.now()
        # Wait 30s for full end
        if (datetime.now() - speech_end_time).seconds > 30:
            return True
    else:
        speech_end_time = None  # Reset
    return False

async def classify_tone(text):
    prompt = f"""
    Classify this central bank speech as exactly one of: Hawkish, Neutral, Dovish.
    Hawkish: Tighter policy, inflation focus, rates high longer.
    Dovish: Easier policy, growth focus, openness to cuts.
    Neutral: Balanced, data-dependent.
    Return ONLY JSON: {{"tone": "Hawkish", "confidence": 0.85, "key_sentences": ["ex1", "ex2"]}}
    Transcript: {text[:20000]}
    """
    try:
        response = await grok.chat.completions.create(
            model="grok-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        import json
        return json.loads(response.choices[0].message.content)
    except:
        return {"tone": "Neutral", "confidence": 0.5, "key_sentences": []}

def send_email(tone, text):
    msg = MIMEText(f"""
    <h2>⚠️ Fed Speech Alert</h2>
    <p><strong>Tone:</strong> {tone['tone']} ({tone['confidence']*100:.0f}%)</p>
    <p><strong>Key Sentences:</strong><ul>{''.join(f'<li>{s}</li>' for s in tone['key_sentences'])}</ul></p>
    <p><em>Full Transcript (snippet):</em><br>{text[:1000]}...</p>
    <p>Full: {URL}</p>
    """, 'html')
    msg['Subject'] = f"Fed Speech Ended: {tone['tone']} – {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    msg['From'] = FROM_EMAIL
    msg['To'] = YOUR_EMAIL

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.starttls()
            server.login(FROM_EMAIL, EMAIL_PASSWORD)
            server.send_message(msg)
        print("Email sent!")
    except Exception as e:
        print(f"Email error: {e}")

async def main():
    global last_text
    print("Monitoring started...")
    while True:
        try:
            html = await fetch_page()
            new_text = extract_speech_text(html)
            if speech_just_ended(new_text):
                tone = await classify_tone(new_text)
                send_email(tone, new_text)
                last_text = ""  # Reset for next
                global speech_end_time
                speech_end_time = None
            last_text = new_text
            await asyncio.sleep(5)  # Check every 5s
        except Exception as e:
            print(f"Error: {e}")
            await asyncio.sleep(10)

if __name__ == "__main__":
    asyncio.run(main())
