import os
import json
import smtplib
import feedparser
import requests
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

SL_TZ = timezone(timedelta(hours=5, minutes=30))

GOOGLE_TRENDS_DAILY_LK = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=LK"
GOOGLE_NEWS_LK = "https://news.google.com/rss?hl=en-LK&gl=LK&ceid=LK:en"

def fetch_rss(url: str, max_items: int = 30) -> list[dict]:
    feed = feedparser.parse(url)
    out = []
    for e in feed.entries[:max_items]:
        out.append({
            "title": getattr(e, "title", ""),
            "link": getattr(e, "link", ""),
            "published": getattr(e, "published", "")
        })
    return out

def gemini_generate(prompt: str) -> str:
    api_key = os.environ["GEMINI_API_KEY"]
    model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.6,
            "maxOutputTokens": 2500
        }
    }
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]

def safe_extract_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        return {"ok": False, "raw": text, "error": "No JSON detected"}
    try:
        return {"ok": True, "report": json.loads(text[start:end+1])}
    except Exception as e:
        return {"ok": False, "raw": text, "error": f"JSON parse failed: {e}"}

def send_email(subject: str, body: str):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    to_email = os.environ["TO_EMAIL"]
    from_email = os.environ.get("FROM_EMAIL", smtp_user)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, [to_email], msg.as_string())

def build_prompt(trends_daily: list[dict], news: list[dict]) -> str:
    today = datetime.now(SL_TZ).strftime("%Y-%m-%d")
    input_blob = {
        "date": today,
        "google_trends_lk_daily": trends_daily,
        "google_news_lk": news
    }

    return f"""
You are a Sri Lanka trend analyst and marketing strategist.

Brands
Group A combined: Studio Nalini + Nalini e shop
Group B separate: Nalini book shop

Goal
Create a Monday report of trends to follow for the coming week in Sri Lanka.

Scoring each trend 0 to 25
Growth 0-5
Sri Lanka relevance 0-5
Brand fit 0-5
Feasibility 0-5 (phone-friendly content)
Risk 0-5 (5 is safest)
Only FOLLOW if total >= 18
Avoid politics, tragedy, hate, misinformation.

Output ONLY valid JSON with this schema:
{{
  "date": "{today}",
  "summary": "",
  "trends": [
    {{
      "name": "",
      "why_trending": "",
      "signals": "",
      "score": {{"growth":0,"sl_relevance":0,"brand_fit":0,"feasibility":0,"risk":0,"total":0}},
      "decision": "FOLLOW or SKIP",
      "groupA_campaign": {{
        "big_idea": "",
        "post_ideas": ["","",""],
        "video_ideas": [
          {{"hook":"","plot":"","script":"","shot_list":["","",""],"caption":"","hashtags":""}},
          {{"hook":"","plot":"","script":"","shot_list":["","",""],"caption":"","hashtags":""}}
        ],
        "weekly_calendar": [
          {{"day":"Mon","content":""}}, {{"day":"Tue","content":""}}, {{"day":"Wed","content":""}},
          {{"day":"Thu","content":""}}, {{"day":"Fri","content":""}}, {{"day":"Sat","content":""}}, {{"day":"Sun","content":""}}
        ],
        "kpis": {{"reach":"","saves":"","clicks":"","dm_inquiries":""}}
      }},
      "groupB_campaign": {{
        "big_idea": "",
        "post_ideas": ["","",""],
        "video_ideas": [
          {{"hook":"","plot":"","script":"","shot_list":["","",""],"caption":"","hashtags":""}},
          {{"hook":"","plot":"","script":"","shot_list":["","",""],"caption":"","hashtags":""}}
        ],
        "weekly_calendar": [
          {{"day":"Mon","content":""}}, {{"day":"Tue","content":""}}, {{"day":"Wed","content":""}},
          {{"day":"Thu","content":""}}, {{"day":"Fri","content":""}}, {{"day":"Sat","content":""}}, {{"day":"Sun","content":""}}
        ],
        "kpis": {{"reach":"","saves":"","store_visits":"","calls":""}}
      }}
    }}
  ],
  "email_subject": "",
  "email_body": ""
}}

Input signals:
{json.dumps(input_blob, ensure_ascii=False)}
"""

def main():
    # Collect signals (fault tolerant)
    trends_daily = fetch_rss(GOOGLE_TRENDS_DAILY_LK, max_items=40)
    news = fetch_rss(GOOGLE_NEWS_LK, max_items=30)

    prompt = build_prompt(trends_daily, news)

    # Gemini attempt 1
    raw = gemini_generate(prompt)
    parsed = safe_extract_json(raw)

    # Gemini attempt 2 if JSON fails (more strict)
    if not parsed["ok"]:
        strict_prompt = "Return ONLY JSON. No markdown. No extra text.\n\n" + prompt
        raw2 = gemini_generate(strict_prompt)
        parsed = safe_extract_json(raw2)

    # If still fails, send debug email so you never miss Monday
    if not parsed["ok"]:
        subject = "Weekly Trend Agent ERROR (JSON parsing failed)"
        body = f"Error: {parsed['error']}\n\nRaw output:\n{parsed['raw'][:8000]}"
        send_email(subject, body)
        return

    report = parsed["report"]
    subject = report.get("email_subject", "Weekly Sri Lanka Trend Report")
    body = report.get("email_body", json.dumps(report, ensure_ascii=False, indent=2))

    send_email(subject, body)

if __name__ == "__main__":
    main()
