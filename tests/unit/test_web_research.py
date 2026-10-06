"""Web research provider adapters and HTML text extraction (mocked HTTP)."""

import json

import httpx
import pytest

from app.web_research.providers import (
    ResearchConfig,
    WebResearchError,
    build_provider,
)
from app.web_research.service import html_to_text


def _config(**overrides: object) -> ResearchConfig:
    base: dict[str, object] = {
        "web_research_provider": "tavily",
        "web_research_base_url": "https://api.test/v1",
        "web_research_api_key": "sk-test",
        "web_research_model": "qwen3.8-flash",
        "web_research_max_results": 5,
        "web_research_timeout_seconds": 30,
        "web_research_max_page_bytes": 1_500_000,
    }
    base.update(overrides)
    return ResearchConfig(base)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


class TestResearchConfig:
    def test_reads_all_fields_and_strips_trailing_slash(self) -> None:
        config = _config(web_research_base_url="https://api.test/v1/")
        assert config.base_url == "https://api.test/v1"
        assert config.provider == "tavily"
        assert config.api_key == "sk-test"
        assert config.max_results == 5

    def test_falls_back_to_defaults(self) -> None:
        config = ResearchConfig({})
        assert config.provider == "tavily"
        assert config.max_results == 5
        assert config.api_key == ""


class TestBuildProvider:
    def test_missing_base_url_raises(self) -> None:
        with pytest.raises(WebResearchError):
            build_provider(_config(web_research_base_url=""))

    def test_apimaster_is_not_a_retrieval_backend(self) -> None:
        """LLM synthesis cannot provide verifiable source URLs — disabled."""

        with pytest.raises(WebResearchError, match="cannot retrieve"):
            build_provider(_config(web_research_provider="apimaster"))

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(WebResearchError, match="unknown web research"):
            build_provider(_config(web_research_provider="mystery"))


class TestTavilyProvider:
    async def test_missing_key_fails_before_request(self) -> None:
        provider = build_provider(
            _config(web_research_api_key=""),
            transport=_transport(lambda request: httpx.Response(200, json={})),
        )
        with pytest.raises(WebResearchError, match="web_research_api_key"):
            await provider.research("q", "")

    async def test_parses_results_and_answer(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/search"
            body = json.loads(request.content)
            assert body["api_key"] == "sk-test"
            assert body["max_results"] == 2
            return httpx.Response(
                200,
                json={
                    "answer": "synthesis",
                    "results": [
                        {
                            "title": "T1",
                            "url": "https://t1.example",
                            "content": "c1",
                        },
                        {"title": "T2", "url": "https://t2.example"},
                        {"title": "no url"},
                    ],
                },
            )

        provider = build_provider(
            _config(
                web_research_provider="tavily",
                web_research_base_url="https://tavily.test",
                web_research_max_results=2,
            ),
            transport=_transport(handler),
        )
        report = await provider.research("q", "")
        assert report.provider == "tavily"
        assert report.answer_text == "synthesis"
        assert [f.url for f in report.findings] == [
            "https://t1.example",
            "https://t2.example",
        ]


class TestCustomProvider:
    async def test_parses_common_result_shapes(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["query"] == "q"
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"link": "https://c.example/1", "name": "One"},
                        {"href": "https://c.example/2", "snippet": "s"},
                    ]
                },
            )

        provider = build_provider(
            _config(
                web_research_provider="custom",
                web_research_base_url="https://search.test/run",
            ),
            transport=_transport(handler),
        )
        report = await provider.research("q", "ctx")
        assert report.provider == "custom"
        assert [f.url for f in report.findings] == [
            "https://c.example/1",
            "https://c.example/2",
        ]
        assert report.findings[0].title == "One"

    async def test_bare_list_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"url": "https://l.example"}])

        provider = build_provider(
            _config(
                web_research_provider="custom",
                web_research_base_url="https://search.test",
            ),
            transport=_transport(handler),
        )
        report = await provider.research("q", "")
        assert [f.url for f in report.findings] == ["https://l.example"]


class TestHtmlToText:
    def test_strips_scripts_and_keeps_block_text(self) -> None:
        html = """
        <html><head><style>body { color: red }</style></head>
        <body>
          <h1>Title</h1>
          <p>First <b>paragraph</b> text.</p>
          <script>var tracker = 1;</script>
          <ul><li>Item one</li><li>Item two</li></ul>
        </body></html>
        """
        text = html_to_text(html)
        assert "Title" in text
        assert "First paragraph text." in text
        assert "Item one" in text and "Item two" in text
        assert "tracker" not in text
        assert "color: red" not in text

    def test_malformed_html_returns_collected_text(self) -> None:
        text = html_to_text("<p>hello<b>world")
        assert "hello" in text and "world" in text


class TestClassifyWebPage:
    """§8 matrix: page-level quality signals from URL + content."""

    def _body(self, n: int = 900) -> str:
        return "By Jane Doe\nPublished 2024\n" + "substantial content. " * n

    def test_scholarly_host(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page(
            "https://pubmed.ncbi.nlm.nih.gov/123", "Study", self._body()
        )
        assert a.publication_type == "scholarly"
        assert a.retrieval_weight == 1.0

    def test_academic_domain(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page("https://www.mit.edu/page", "Lab", self._body())
        assert a.publication_type == "institutional"
        assert a.retrieval_weight == 1.0

    def test_wikipedia_is_tertiary_with_caution(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page(
            "https://en.wikipedia.org/wiki/Resilience", "Wiki", self._body()
        )
        assert a.publication_type == "tertiary_overview"
        assert a.retrieval_weight < 1.0
        assert any("tertiary" in c for c in a.cautions)

    def test_press_release_downgraded(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page(
            "https://www.eurekalert.org/news/1", "Breakthrough!", self._body()
        )
        assert a.publication_type == "press_release"
        assert a.retrieval_weight < 0.9

    def test_journalism_is_secondary(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page(
            "https://www.theguardian.com/science/x", "Report", self._body()
        )
        assert a.publication_type == "journalism"
        assert any("secondary" in c for c in a.cautions)

    def test_personal_blog_downgraded(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page(
            "https://someone.medium.com/post", "My take", self._body()
        )
        assert a.publication_type == "personal_blog"
        assert a.retrieval_weight < 0.9

    def test_affiliate_seo_phrasing_penalised(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page(
            "https://shop.example.com/list",
            "Top 10 best supplements 2025 — promo code inside",
            self._body(),
        )
        assert any("affiliate" in c for c in a.cautions)
        assert a.retrieval_weight < 0.8

    def test_thin_content_penalised(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page(
            "https://x.example.com", "T", "short text 2024 by Jane Doe"
        )
        assert any("thin" in c for c in a.cautions)

    def test_unknown_host_stays_unclassified_not_bad(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page("https://random-site.io/x", "T", self._body())
        assert a.publication_type == "web_page"
        assert "verify" in a.review_notes

    def test_notes_always_explain_signals(self) -> None:
        from app.web_research.classify import classify_web_page

        a = classify_web_page("https://nature.com/a", "T", self._body())
        assert "signals:" in a.review_notes
        assert "Heuristic" in a.review_notes
