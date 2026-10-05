"""Heuristic source-quality assessment for fetched web pages.

This is deliberately NOT a GOOD/BAD classifier. It records observable
signals — what kind of page this is, how much caution it warrants, and
why — into ``knowledge.source_quality`` so downstream review and the
owner can see the difference between a university page and a personal
blog. ``retrieval_weight`` is a persisted hint (currently advisory: the
retrieval ranker does not consume it yet); ``review_notes`` always lists
the signals the decision was based on so nothing is opaque.

Channel policy stays out of scope here: Science prioritising scholarly
sources or History legitimising primary archival material is a
strategy-level concern, not a page-level classification.
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

# Domain suffixes → (publication_type, base weight, note).
_ACADEMIC_HOSTS = {
    "pubmed.ncbi.nlm.nih.gov",
    "doi.org",
    "arxiv.org",
    "biorxiv.org",
    "medrxiv.org",
    "ssrn.com",
    "nature.com",
    "science.org",
    "sciencedirect.com",
    "springer.com",
    "link.springer.com",
    "wiley.com",
    "onlinelibrary.wiley.com",
    "tandfonline.com",
    "jstor.org",
    "plos.org",
    "frontiersin.org",
    "bmj.com",
    "thelancet.com",
    "psycnet.apa.org",
    "philpapers.org",
    "plato.stanford.edu",
}
_TERTIARY_HOSTS = {"wikipedia.org", "britannica.com"}
_JOURNALISM_HOSTS = {
    "bbc.com",
    "bbc.co.uk",
    "reuters.com",
    "apnews.com",
    "nytimes.com",
    "theguardian.com",
    "washingtonpost.com",
    "economist.com",
    "ft.com",
    "spiegel.de",
    "zeit.de",
    "sueddeutsche.de",
    "faz.net",
    "npr.org",
    "dw.com",
    "scientificamerican.com",
    "newscientist.com",
    "nationalgeographic.com",
    "atlantic.com",
    "theatlantic.com",
}
_BLOG_PLATFORMS = {
    "medium.com",
    "substack.com",
    "blogspot.com",
    "wordpress.com",
    "tumblr.com",
    "ghost.io",
    "telegra.ph",
    "blogfa.com",
    "persianblog.ir",
    "virgool.io",
}
# Press-release / PR-wire hosts: legitimate but notoriously overstated.
_PRESS_RELEASE_HOSTS = {
    "prnewswire.com",
    "businesswire.com",
    "globenewswire.com",
    "eurekalert.org",
    "newswise.com",
}

_AFFILIATE_RE = re.compile(
    r"(?i)\b(top\s+\d+\s+best|best\s+\w+\s+of\s+\d{4}|affiliate|"
    r"sponsored\s+(post|content)|coupon|promo\s+code|discount\s+code|"
    r"buy\s+now|limited[-\s]time\s+offer)\b"
)
_DATE_RE = re.compile(r"\b(19|20)\d{2}\b")
_AUTHOR_RE = re.compile(
    r"(?im)^.{0,40}\bby\s+[A-ZÄÖÜ][a-zäöü]+\s+[A-ZÄÖÜ][a-zäöü]+", re.M
)


@dataclass(frozen=True)
class WebSourceAssessment:
    """Observable quality signals for one fetched page."""

    publication_type: str
    retrieval_weight: float
    signals: tuple[str, ...]
    cautions: tuple[str, ...]

    @property
    def review_notes(self) -> str:
        parts = [f"signals: {', '.join(self.signals)}"]
        if self.cautions:
            parts.append(f"cautions: {', '.join(self.cautions)}")
        parts.append(
            "Heuristic classification from URL + page text; "
            "verify before relying on this source as evidence."
        )
        return "; ".join(parts)


def _registrable(host: str) -> str:
    """Last two labels of a hostname ('en.wikipedia.org' → 'wikipedia.org')."""

    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def classify_web_page(url: str, title: str, text: str) -> WebSourceAssessment:
    """Classify one fetched page from observable URL + content signals."""

    host = urlparse(url).hostname or ""
    host = host.removeprefix("www.").lower()
    registrable = _registrable(host)
    signals: list[str] = []
    cautions: list[str] = []

    if host in _ACADEMIC_HOSTS or registrable in _ACADEMIC_HOSTS:
        publication_type, weight = "scholarly", 1.0
        signals.append("scholarly host")
    elif registrable in _TERTIARY_HOSTS:
        publication_type, weight = "tertiary_overview", 0.75
        signals.append("encyclopedic overview host")
        cautions.append("tertiary source — trace claims to cited primary works")
    elif registrable in _PRESS_RELEASE_HOSTS:
        publication_type, weight = "press_release", 0.6
        signals.append("press-release host")
        cautions.append("press releases routinely overstate study findings")
    elif registrable in _JOURNALISM_HOSTS:
        publication_type, weight = "journalism", 0.9
        signals.append("established journalism host")
        cautions.append("secondary reporting — verify against the cited study")
    elif host.endswith(".edu") or host.endswith(".gov") or ".ac." in host:
        publication_type, weight = "institutional", 1.0
        signals.append("academic/government domain")
    elif registrable in _BLOG_PLATFORMS:
        publication_type, weight = "personal_blog", 0.6
        signals.append("self-publishing platform")
        cautions.append("no editorial review on self-publishing platforms")
    else:
        publication_type, weight = "web_page", 0.8
        signals.append("unclassified host")
        cautions.append("source type not identified — assess manually")

    if _AFFILIATE_RE.search(title) or _AFFILIATE_RE.search(text[:4000]):
        cautions.append("affiliate/SEO-style phrasing detected")
        weight *= 0.7
    if not _AUTHOR_RE.search(text[:2000]):
        cautions.append("no identifiable author byline")
        weight *= 0.9
    if len(text) < 800:
        cautions.append("thin page content")
        weight *= 0.8
    if not _DATE_RE.search(text[:3000]):
        cautions.append("no date found in page content — recency unverifiable")

    return WebSourceAssessment(
        publication_type=publication_type,
        retrieval_weight=round(min(weight, 1.0), 3),
        signals=tuple(signals),
        cautions=tuple(cautions),
    )
