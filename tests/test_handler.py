"""
Unit tests for Tech Trend Radar Lambda handler.
All external calls (AWS, Groq, HTTP) are mocked.
"""

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Environment setup (must happen before importing handler) ──────────────────
os.environ.setdefault("RECIPIENT_EMAIL", "test@example.com")
os.environ.setdefault("SENDER_EMAIL", "sender@example.com")
os.environ.setdefault("GROQ_API_KEY_PARAM", "/tech-trend-radar/groq-api-key")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_REGION", "us-east-1")
os.environ.setdefault("HN_TOP_N", "5")
os.environ.setdefault("GITHUB_TOP_N", "3")
os.environ.setdefault("REDDIT_TOP_N", "5")

sys.path.insert(0, "lambda/src")


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_hn_response():
    return [1, 2, 3]


@pytest.fixture
def mock_hn_story():
    return {
        "type": "story",
        "title": "Llama 4 beats GPT-5 on all benchmarks",
        "score": 500,
        "url": "https://example.com/llama4",
        "descendants": 200,
    }


@pytest.fixture
def mock_github_response():
    return [
        {
            "author": "openai",
            "name": "triton",
            "description": "OpenAI Triton compiler",
            "stars": 1200,
            "language": "Python",
            "url": "https://github.com/openai/triton",
        }
    ]


@pytest.fixture
def mock_reddit_response():
    return {
        "data": {
            "children": [
                {
                    "data": {
                        "title": "Terraform 2.0 released with huge performance improvements",
                        "score": 800,
                        "num_comments": 120,
                        "permalink": "/r/devops/comments/abc123/",
                        "stickied": False,
                    }
                }
            ]
        }
    }


@pytest.fixture
def mock_groq_analysis():
    return """🔥 Llama 4 Open Source Dominance
Why it's hot: Meta's Llama 4 has surpassed GPT-5 on multiple benchmarks.
Get in now because: Open source LLMs are becoming enterprise-grade rapidly.
Signal strength: HIGH | Sources: Hacker News, Reddit

Bottom Line: Open source AI is having its biggest week ever."""


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestFetchHackerNews:
    @patch("handler.requests.get")
    def test_returns_stories(self, mock_get, mock_hn_response, mock_hn_story):
        responses = [MagicMock(json=lambda: mock_hn_response)]
        for _ in mock_hn_response:
            responses.append(MagicMock(json=lambda s=mock_hn_story: s))
        mock_get.side_effect = responses

        import handler
        stories = handler.fetch_hacker_news()

        assert len(stories) == 3
        assert stories[0]["source"] == "Hacker News"
        assert "title" in stories[0]
        assert "score" in stories[0]

    @patch("handler.requests.get", side_effect=Exception("Network error"))
    def test_returns_empty_on_failure(self, _):
        import handler
        stories = handler.fetch_hacker_news()
        assert stories == []


class TestFetchGitHubTrending:
    @patch("handler.requests.get")
    def test_returns_repos(self, mock_get, mock_github_response):
        mock_get.return_value = MagicMock(json=lambda: mock_github_response)

        import handler
        repos = handler.fetch_github_trending()

        assert len(repos) == 1
        assert repos[0]["source"] == "GitHub Trending"
        assert repos[0]["title"] == "openai/triton"

    @patch("handler.requests.get", side_effect=Exception("Timeout"))
    def test_returns_empty_on_failure(self, _):
        import handler
        repos = handler.fetch_github_trending()
        assert repos == []


class TestFetchReddit:
    @patch("handler.requests.get")
    def test_returns_posts(self, mock_get, mock_reddit_response):
        mock_get.return_value = MagicMock(json=lambda: mock_reddit_response)

        import handler
        posts = handler.fetch_reddit_tech()

        assert len(posts) > 0
        assert "source" in posts[0]
        assert posts[0]["title"] == "Terraform 2.0 released with huge performance improvements"


class TestAnalyzeWithGroq:
    def test_returns_analysis_string(self, mock_groq_analysis):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content=mock_groq_analysis))]
        )

        with patch("handler.Groq", return_value=mock_client):
            import handler
            result = handler.analyze_with_groq(
                {"hn": [{"title": "test", "score": 100}], "github": [], "reddit": []},
                "fake-key",
            )

        assert "🔥" in result
        assert len(result) > 50


class TestBuildEmailHtml:
    def test_returns_subject_html_plain(self, mock_groq_analysis):
        import handler
        raw_data = {"hn": [{}] * 5, "github": [{}] * 2, "reddit": [{}] * 3}
        subject, html, plain = handler.build_email_html(mock_groq_analysis, raw_data)

        assert "Tech Trend Radar" in subject
        assert "<!DOCTYPE html>" in html
        assert "Llama 4" in plain


class TestLambdaHandler:
    @patch("handler.send_email")
    @patch("handler.analyze_with_groq")
    @patch("handler.get_groq_key", return_value="fake-key")
    @patch("handler.fetch_reddit_tech")
    @patch("handler.fetch_github_trending")
    @patch("handler.fetch_hacker_news")
    def test_successful_run(
        self,
        mock_hn,
        mock_gh,
        mock_reddit,
        mock_key,
        mock_analyze,
        mock_send,
        mock_groq_analysis,
    ):
        mock_hn.return_value = [{"title": "Test HN", "score": 100, "url": "http://x.com", "comments": 10, "source": "Hacker News"}]
        mock_gh.return_value = [{"title": "user/repo", "description": "desc", "stars": 50, "language": "Go", "url": "http://github.com", "source": "GitHub Trending"}]
        mock_reddit.return_value = [{"title": "Test Reddit", "score": 200, "comments": 30, "url": "http://reddit.com", "source": "r/devops"}]
        mock_analyze.return_value = mock_groq_analysis

        import handler
        response = handler.lambda_handler({}, {})

        assert response["statusCode"] == 200
        body = json.loads(response["body"])
        assert body["message"] == "Digest sent successfully"
        mock_send.assert_called_once()

    @patch("handler.fetch_hacker_news", return_value=[])
    @patch("handler.fetch_github_trending", return_value=[])
    @patch("handler.fetch_reddit_tech", return_value=[])
    def test_raises_when_all_scrapers_fail(self, *_):
        import handler
        with pytest.raises(RuntimeError, match="All scrapers returned empty"):
            handler.lambda_handler({}, {})
