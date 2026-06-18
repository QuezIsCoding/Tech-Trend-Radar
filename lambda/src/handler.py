"""
Tech Trend Radar - Lambda Handler
Scrapes trending tech topics from multiple sources,
analyzes them with Groq (Llama 3), and sends a digest email via SES.
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

# ── Config (from env vars set by Terraform / GitHub Actions) ──────────────────
RECIPIENT_EMAIL = os.environ["RECIPIENT_EMAIL"]
SENDER_EMAIL    = os.environ["SENDER_EMAIL"]
GROQ_API_KEY_PARAM = os.environ["GROQ_API_KEY_PARAM"]   # SSM param name
HN_TOP_N        = int(os.environ.get("HN_TOP_N", "30"))
GITHUB_TOP_N    = int(os.environ.get("GITHUB_TOP_N", "10"))
REDDIT_TOP_N    = int(os.environ.get("REDDIT_TOP_N", "15"))


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_groq_key() -> str:
    """Fetch Groq API key from SSM Parameter Store (SecureString)."""
    response = ssm_client.get_parameter(Name=GROQ_API_KEY_PARAM, WithDecryption=True)
    return response["Parameter"]["Value"]


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
                    "source": "Hacker News",
                    "title": item.get("title", ""),
                    "score": item.get("score", 0),
                    "url":   item.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                    "comments": item.get("descendants", 0),
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
                "source": "GitHub Trending",
                "title":       f"{repo.get('author', '')}/{repo.get('name', '')}",
                "description": repo.get("description", "No description"),
                "stars":       repo.get("stars", 0),
                "language":    repo.get("language", "Unknown"),
                "url":         repo.get("url", ""),
            })
        logger.info("Fetched %d GitHub trending repos", len(results))
        return results
    except Exception as exc:
        logger.error("GitHub trending fetch failed: %s", exc)
        return []


def fetch_reddit_tech() -> list[dict]:
    """Pull hot posts from r/programming, r/devops, r/MachineLearning."""
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
                        "source":    f"r/{sub}",
                        "title":     post.get("title", ""),
                        "score":     post.get("score", 0),
                        "comments":  post.get("num_comments", 0),
                        "url":       f"https://reddit.com{post.get('permalink', '')}",
                    })
            logger.info("Fetched posts from r/%s", sub)
        except Exception as exc:
            logger.error("Reddit r/%s fetch failed: %s", sub, exc)

    return posts


# ── Analysis ───────────────────────────────────────────────────────────────────

def analyze_with_groq(raw_data: dict, groq_key: str) -> str:
    """Send scraped data to Groq Llama 3 for trend analysis."""
    logger.info("Sending data to Groq for analysis...")
    client = Groq(api_key=groq_key)

    # Build a compact prompt — cheaper and faster
    hn_titles    = [f"- {s['title']} (score: {s['score']})" for s in raw_data["hn"][:20]]
    github_repos = [f"- {r['title']} [{r.get('language','')}]: {r.get('description','')}" for r in raw_data["github"]]
    reddit_posts = [f"- [{s['source']}] {s['title']} (score: {s['score']})" for s in raw_data["reddit"][:20]]

    prompt = f"""You are a senior tech analyst. Below is raw data scraped from Hacker News, GitHub Trending, and Reddit tech communities collected on {datetime.now(timezone.utc).strftime('%B %d, %Y')}.

Your job: identify the 5-7 HOTTEST tech trends that developers and engineers should know about RIGHT NOW. Focus on "get in now" signals — things gaining momentum fast, not already-mainstream topics.

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
Signal strength: [HIGH / MEDIUM] | Sources: [where you saw it]

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


# ── Email ──────────────────────────────────────────────────────────────────────

def build_email_html(analysis: str, raw_data: dict) -> tuple[str, str]:
    """Build HTML + plain text email from the Groq analysis."""
    date_str = datetime.now(timezone.utc).strftime("%B %d, %Y")
    subject  = f"🔥 Tech Trend Radar — {date_str}"

    # Convert trend blocks to styled HTML cards
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
            # Bottom line section
            html_analysis += f"""
            <div style="background:#0f3460;border-radius:8px;padding:16px 20px;
                        margin-top:24px;color:#e0e0f0;font-size:14px;line-height:1.6;">
              <strong style="color:#e94560;">📊 Bottom Line</strong><br>{block.strip()}
            </div>"""

    # Quick stats bar
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

    <!-- Header -->
    <div style="text-align:center;padding:32px 0 24px;">
      <div style="font-size:28px;font-weight:800;color:#ffffff;letter-spacing:-0.5px;">
        📡 Tech Trend Radar
      </div>
      <div style="color:#6060a0;font-size:13px;margin-top:6px;">{date_str} · Every 2 Days</div>
    </div>

    <!-- Stats -->
    {stats_html}

    <!-- Analysis -->
    <div style="margin-bottom:32px;">{html_analysis}</div>

    <!-- Footer -->
    <div style="border-top:1px solid #1a1a3a;padding-top:16px;text-align:center;
                color:#404060;font-size:11px;">
      Tech Trend Radar · Powered by Groq Llama 3 · Built on AWS<br>
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
        # 1. Scrape all sources in parallel-ish (sequential is fine at this scale)
        raw_data = {
            "hn":     fetch_hacker_news(),
            "github": fetch_github_trending(),
            "reddit": fetch_reddit_tech(),
        }

        total_items = sum(len(v) for v in raw_data.values())
        logger.info("Total items scraped: %d", total_items)

        if total_items == 0:
            raise RuntimeError("All scrapers returned empty — aborting to avoid blank email")

        # 2. Analyze with Groq
        groq_key = get_groq_key()
        analysis = analyze_with_groq(raw_data, groq_key)

        # 3. Build + send email
        subject, html_body, plain_text = build_email_html(analysis, raw_data)
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
