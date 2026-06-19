"""
Tech Trend Radar - Lambda Handler
Scrapes trending tech topics from multiple sources,
analyzes them with Groq (Llama 3.3), and sends a digest email via SES.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone

import boto3
import requests
from groq import Groq

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── Clients ────────────────────────────────────────────────────────────────────
ses_client = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
ssm_client = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))

# ── Config ─────────────────────────────────────────────────────────────────────
RECIPIENT_EMAIL    = os.environ["RECIPIENT_EMAIL"]
SENDER_EMAIL       = os.environ["SENDER_EMAIL"]
GROQ_API_KEY_PARAM = os.environ["GROQ_API_KEY_PARAM"]
HN_TOP_N           = int(os.environ.get("HN_TOP_N", "30"))
GITHUB_TOP_N       = int(os.environ.get("GITHUB_TOP_N", "10"))
REDDIT_TOP_N       = int(os.environ.get("REDDIT_TOP_N", "15"))

# Max characters per scraped title to prevent prompt injection
MAX_TITLE_LENGTH = 200


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_groq_key() -> str:
    """Fetch Groq API key from SSM Parameter Store (SecureString)."""
    response = ssm_client.get_parameter(Name=GROQ_API_KEY_PARAM, WithDecryption=True)
    return response["Parameter"]["Value"]


def sanitize(text: str, max_length: int = MAX_TITLE_LENGTH) -> str:
    """Sanitize scraped text to prevent prompt injection.
    - Strips leading/trailing whitespace
    - Removes newlines and control characters
    - Truncates to max_length
    - Removes common prompt injection patterns
    """
    if not text:
        return ""
    # Remove newlines and control characters
    text = re.sub(r"[\r\n\t\x00-\x1f\x7f]", " ", text)
    # Remove common prompt injection patterns
    text = re.sub(r"(?i)(ignore|disregard|forget).{0,30}(instructions?|above|previous)", "", text)
    text = re.sub(r"(?i)(you are|act as|pretend|roleplay|system prompt)", "", text)
    # Collapse multiple spaces
    text = re.sub(r" +", " ", text).strip()
    # Truncate
    return text[:max_length]


# ── Scrapers ───────────────────────────────────────────────────────────────────

def fetch_hacker_news() -> list[dict]:
    """Pull top HN stories and return title + score + url."""
    logger.info("Fetching Hacker News top stories...")
    try:
        top_ids = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json", timeout=10
        ).json()[:HN_TOP_N]

        stories = []
        for story_id in top_ids:
            item = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json", timeout=5
            ).json()
            if item and item.get("type") == "story":
                stories.append({
                    "source":   "Hacker News",
                    "title":    sanitize(item.get("title", "")),
                    "score":    int(item.get("score", 0)),
                    "url":      item.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                    "comments": int(item.get("descendants", 0)),
                })
        logger.info("Fetched %d HN stories", len(stories))
        return stories
    except Exception as exc:
        logger.error("HN fetch failed: %s", exc)
        return []


def fetch_github_trending() -> list[dict]:
    """Scrape GitHub trending repos via the unofficial trending API."""
    logger.info("Fetching GitHub trending repos...")
    try:
        response = requests.get(
            "https://api.gitterapp.com/repositories?since=daily",
            timeout=10,
            headers={"Accept": "application/json"},
        )
        repos = response.json()[:GITHUB_TOP_N]
        results = []
        for repo in repos:
            results.append({
                "source":      "GitHub Trending",
                "title":       sanitize(f"{repo.get('author', '')}/{repo.get('name', '')}"),
                "description": sanitize(repo.get("description", "No description")),
                "stars":       int(repo.get("stars", 0)),
                "language":    sanitize(repo.get("language", "Unknown"), max_length=50),
                "url":         repo.get("url", ""),
            })
        logger.info("Fetched %d GitHub trending repos", len(results))
        return results
    except Exception as exc:
        logger.error("GitHub trending fetch failed: %s", exc)
        return []


def fetch_reddit_tech() -> list[dict]:
    """Pull hot posts from tech subreddits."""
    subreddits = ["programming", "devops", "MachineLearning", "aws", "webdev"]
    posts = []
    headers = {"User-Agent": "TechTrendRadar/1.0 (public project)"}

    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit={REDDIT_TOP_N}"
            data = requests.get(url, headers=headers, timeout=10).json()
            for child in data.get("data", {}).get("children", []):
                post = child.get("data", {})
                if not post.get("stickied"):
                    posts.append({
                        "source":   f"r/{sub}",
                        "title":    sanitize(post.get("title", "")),
                        "score":    int(post.get("score", 0)),
                        "comments": int(post.get("num_comments", 0)),
                        "url":      f"https://reddit.com{post.get('permalink', '')}",
                    })
            logger.info("Fetched posts from r/%s", sub)
        except Exception as exc:
            logger.error("Reddit r/%s fetch failed: %s", sub, exc)

    return posts


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyze_with_groq(raw_data: dict, groq_key: str) -> str:
    """Send scraped data to Groq Llama 3.3 for trend analysis."""
    logger.info("Sending data to Groq for analysis...")
    client = Groq(api_key=groq_key)

    hn_titles    = [f"- {s['title']} (score: {s['score']})" for s in raw_data["hn"][:20]]
    github_repos = [f"- {r['title']} [{r.get('language', '')}]: {r.get('description', '')}" for r in raw_data["github"]]
    reddit_posts = [f"- [{s['source']}] {s['title']} (score: {s['score']})" for s in raw_data["reddit"][:20]]

    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")

    prompt = f"""You are a senior tech analyst. Below is raw data scraped from Hacker News, GitHub Trending, and Reddit tech communities collected on {date_str}.

Your job: identify the 5-7 HOTTEST tech trends that developers and engineers should know about RIGHT NOW. Focus on "get in now" signals — things gaining momentum fast, not already-mainstream topics.

IMPORTANT: Only report trends that are directly supported by the data below. Do not invent, hallucinate, or assume trends not present in the source data. If you are uncertain, say so.

--- HACKER NEWS TOP STORIES ---
{chr(10).join(hn_titles)}

--- GITHUB TRENDING TODAY ---
{chr(10).join(github_repos)}

--- REDDIT HOT POSTS ---
{chr(10).join(reddit_posts)}

Respond in this EXACT format for each trend:

🔥 TREND NAME
Why it's hot: [2-3 sentences on what's happening and why it matters]
Get in now because: [1-2 sentences on the opportunity or timing signal]
Signal strength: [HIGH / MEDIUM] | Sources: [exact titles from the data above that support this trend]

End with a 2-sentence "Bottom Line" summary of the overall tech landscape this week.
"""

    chat = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.6,
        max_tokens=1500,
    )
    result = chat.choices[0].message.content
    logger.info("Groq analysis complete (%d chars)", len(result))
    return result


def verify_analysis(analysis: str, raw_data: dict, groq_key: str) -> str:
    """Second-pass hallucination check using a fast model.
    Verifies each trend claim is grounded in the scraped source data.
    Removes or flags any trend not supported by actual sources.
    """
    logger.info("Running hallucination verification pass...")
    client = Groq(api_key=groq_key)

    all_titles = (
        [s["title"] for s in raw_data["hn"]]
        + [r["title"] for r in raw_data["github"]]
        + [p["title"] for p in raw_data["reddit"]]
    )
    source_list = "\n".join(f"- {t}" for t in all_titles if t)

    verify_prompt = f"""You are a fact-checker for a tech newsletter. Below is an AI-generated trend analysis, followed by the ACTUAL source data it was based on.

Your job: Review each 🔥 trend block. If a trend is supported by at least one actual source title below, keep it unchanged. If a trend appears to be invented or not supported by any source title, remove that entire trend block.

Return ONLY the verified trend blocks in the same format. Do not add commentary. Do not invent new trends. Do not modify trends that are supported.

--- AI ANALYSIS TO VERIFY ---
{analysis}

--- ACTUAL SOURCE DATA ---
{source_list[:3000]}
"""

    verify_chat = client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[{"role": "user", "content": verify_prompt}],
        temperature=0.1,
        max_tokens=1500,
    )
    verified = verify_chat.choices[0].message.content
    logger.info("Verification complete (%d chars)", len(verified))
    return verified


# ── Email ──────────────────────────────────────────────────────────────────────

def build_email_html(analysis: str, raw_data: dict) -> tuple[str, str, str]:
    """Build HTML + plain text email from the verified analysis."""
    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    subject  = f"🔥 Tech Trend Radar — {date_str}"

    html_analysis = ""
    blocks = re.split(r"\n(?=🔥)", analysis.strip())
    for block in blocks:
        if block.startswith("🔥"):
            lines = block.strip().split("\n")
            title = lines[0].replace("🔥", "").strip()
            body  = "<br>".join(lines[1:])
            html_analysis += f"""
            <div style="background:#1a1a2e;border-left:4px solid #e94560;
                        border-radius:8px;padding:16px 20px;margin-bottom:16px;">
              <div style="color:#e94560;font-weight:700;font-size:16px;margin-bottom:8px;">
                🔥 {title}
              </div>
              <div style="color:#c0c0d0;font-size:14px;line-height:1.6;">{body}</div>
            </div>"""
        else:
            html_analysis += f"""
            <div style="background:#0f3460;border-radius:8px;padding:16px 20px;
                        margin-top:24px;color:#e0e0f0;font-size:14px;line-height:1.6;">
              <strong style="color:#e94560;">📊 Bottom Line</strong><br>{block.strip()}
            </div>"""

    stats_html = f"""
    <div style="display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap;">
      <span style="background:#16213e;color:#a0a0c0;padding:6px 12px;border-radius:20px;font-size:12px;">
        📰 {len(raw_data['hn'])} HN Stories
      </span>
      <span style="background:#16213e;color:#a0a0c0;padding:6px 12px;border-radius:20px;font-size:12px;">
        ⭐ {len(raw_data['github'])} GitHub Repos
      </span>
      <span style="background:#16213e;color:#a0a0c0;padding:6px 12px;border-radius:20px;font-size:12px;">
        💬 {len(raw_data['reddit'])} Reddit Posts
      </span>
    </div>"""

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#0d0d1a;font-family:'Segoe UI',Arial,sans-serif;">
  <div style="max-width:640px;margin:0 auto;padding:24px 16px;">
    <div style="text-align:center;padding:32px 0 24px;">
      <div style="font-size:28px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">
        📡 Tech Trend Radar
      </div>
      <div style="color:#6060a0;font-size:13px;margin-top:6px;">{date_str} · Every 2 Days</div>
    </div>
    {stats_html}
    <div style="margin-bottom:32px;">{html_analysis}</div>
    <div style="border-top:1px solid #1a1a3a;padding-top:16px;text-align:center;
                color:#404060;font-size:11px;">
      Tech Trend Radar · Powered by Groq Llama 3.3 · Verified · Built on AWS<br>
      Sources: Hacker News · GitHub Trending · Reddit
    </div>
  </div>
</body>
</html>"""

    plain_text = f"Tech Trend Radar — {date_str}\n\n{analysis}\n\nSources: Hacker News, GitHub Trending, Reddit"
    return subject, html_body, plain_text


def send_email(subject: str, html_body: str, plain_text: str) -> None:
    """Send the digest via Amazon SES."""
    logger.info("Sending email to %s via SES...", RECIPIENT_EMAIL)
    ses_client.send_email(
        Source=SENDER_EMAIL,
        Destination={"ToAddresses": [RECIPIENT_EMAIL]},
        Message={
            "Subject": {"Data": subject, "Charset": "UTF-8"},
            "Body": {
                "Text": {"Data": plain_text, "Charset": "UTF-8"},
                "Html": {"Data": html_body,  "Charset": "UTF-8"},
            },
        },
    )
    logger.info("Email sent successfully")


# ── Entry Point ────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    """Main Lambda entry point."""
    logger.info("Tech Trend Radar triggered at %s", datetime.now(timezone.utc).isoformat())

    try:
        # 1. Scrape all sources
        raw_data = {
            "hn":     fetch_hacker_news(),
            "github": fetch_github_trending(),
            "reddit": fetch_reddit_tech(),
        }

        total_items = sum(len(v) for v in raw_data.values())
        logger.info("Total items scraped: %d", total_items)

        if total_items == 0:
            raise RuntimeError("All scrapers returned empty — aborting to avoid blank email")

        # 2. Analyze with Groq Llama 3.3
        groq_key = get_groq_key()
        analysis = analyze_with_groq(raw_data, groq_key)

        # 3. Verify analysis against source data (hallucination check)
        verified_analysis = verify_analysis(analysis, raw_data, groq_key)

        # 4. Build + send email
        subject, html_body, plain_text = build_email_html(verified_analysis, raw_data)
        send_email(subject, html_body, plain_text)

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Digest sent successfully",
                "items_scraped": total_items,
                "recipient": RECIPIENT_EMAIL,
            }),
        }

    except Exception as exc:
        logger.exception("Tech Trend Radar failed: %s", exc)
        raise
