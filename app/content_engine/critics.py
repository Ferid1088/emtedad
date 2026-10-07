"""Specialized script critics — each role has its own brief and its own
model role, and all of them run in parallel.

Inspired by the TrueCrime pipeline (specialized critics, native-language
criteria written in the target language, deterministic script gates),
adapted to Emtedad's content: philosophy, mysticism, religion, culture.
"""

import re
from dataclasses import dataclass

from app.content_engine.domain import CriticRole
from app.knowledge.llm.roles import AgentRole

CRITIC_PROMPT_VERSION_V3 = "critic_v3_specialized"

_COMMON = (
    "You are the {name} for one Emtedad production (a spoken lecture/"
    "documentary script). Judge ONLY your own dimension — other critics "
    "cover the rest. Report findings only, never rewrite the script. Each "
    "finding: location (exact quote or section reference), code, severity "
    "(INFO | WARNING | BLOCKER), explanation, correction_constraint (what a "
    "fix must achieve, without dictating wording). Use BLOCKER only when "
    "the script must not be published as is. Report nothing rather than "
    "invent problems.{checks}"
)

_FOCUS: dict[CriticRole, str] = {
    CriticRole.FACT: (
        "Focus: factual and textual accuracy. Every claim, date, name, "
        "attribution, quotation and number must be supported by the evidence "
        "and plan in the context. Flag invented details, misattributed "
        "quotes (especially of poets, mystics and philosophers), paraphrases "
        "presented as direct quotes, disputed points stated as settled, and "
        "uncertainty that was dropped."
    ),
    CriticRole.LOGIC: (
        "Focus: argument and reasoning. Does each step follow from the "
        "previous one? Flag circular reasoning, leaps, unsupported "
        "generalisations, strawman versions of opposing views, conclusions "
        "that go further than the evidence, and counterarguments that are "
        "announced but never answered."
    ),
    CriticRole.CHANNEL_SPECIFIC: (
        "Focus: fit with the channel's editorial strategy, audience and "
        "tone in the context, and the listed channel checks. Flag passages "
        "that preach instead of explain, talk down to the audience, or drift "
        "from the brief's question and thesis."
    ),
    CriticRole.RETENTION: (
        "Focus: engagement for a spoken video. Is there a strong opening "
        "question or tension in the first lines? Does every section give the "
        "listener a reason to keep listening (open question, contrast, "
        "concrete example, story)? Flag long abstract stretches, repetition, "
        "lists read aloud, weak transitions and a flat ending."
    ),
    CriticRole.ORIGINALITY: (
        "Focus: originality and source distance. Flag passages that copy "
        "or closely paraphrase a source's sentences or structure, generic "
        "filler any channel could say, and clichés. Quotations that are "
        "marked and attributed are allowed."
    ),
    CriticRole.PERSIAN_QUALITY: (
        "Focus: native Persian quality of a text that will be SPOKEN. "
        "Judge in Persian, as a native Persian writer and narrator would — "
        "do not compare with any other language.\n"
        "معیارها:\n"
        "- آیا متن واقعاً طبیعی و بومی است، یا بوی ترجمه می‌دهد؟\n"
        "- آیا جمله‌بندی فارسی طبیعی است (ترتیب اجزای جمله، فعل‌ها)؟\n"
        "- آیا برای شنیدن نوشته شده — جمله‌های قابل خواندن با یک نفس؟\n"
        "- آیا ریتم روایت برای ویدیو مناسب است؟\n"
        "- آیا واژه‌ها و اصطلاحات دقیق و طبیعی‌اند؛ اصطلاحات عرفانی و "
        "فلسفی درست به کار رفته‌اند؟\n"
        "- آیا متن بیش از حد رسمی، کتابی یا خشک شده است؟\n"
        "- آیا واژه‌های بیگانهٔ غیرضروری یا خط لاتین در متن هست؟\n"
        "- آیا متن حس نویسندهٔ فارسی‌زبان را دارد؟\n"
        "Write explanation and correction_constraint in Persian."
    ),
}

# Which model role answers each critic. Reasoning-heavy checks go to the
# professional reasoning model, language/engagement checks to the
# multilingual editorial model.
CRITIC_AGENT_ROLES: dict[CriticRole, AgentRole] = {
    CriticRole.FACT: AgentRole.FACT_CRITIC,
    CriticRole.LOGIC: AgentRole.EPISTEMIC_CRITIC,
    CriticRole.CHANNEL_SPECIFIC: AgentRole.FIDELITY_CRITIC,
    CriticRole.RETENTION: AgentRole.AUDIENCE_RETENTION_CRITIC,
    CriticRole.ORIGINALITY: AgentRole.FIDELITY_CRITIC,
    CriticRole.PERSIAN_QUALITY: AgentRole.NATIVE_SPOKEN_CRITIC,
}

_NAMES = {
    CriticRole.FACT: "fact critic",
    CriticRole.LOGIC: "logic critic",
    CriticRole.CHANNEL_SPECIFIC: "channel critic",
    CriticRole.RETENTION: "engagement critic",
    CriticRole.ORIGINALITY: "originality critic",
    CriticRole.PERSIAN_QUALITY: "Persian language critic",
}


def critic_instructions(role: CriticRole, checks: tuple[str, ...]) -> str:
    listed = f" Channel checks: {', '.join(checks)}." if checks else ""
    return _COMMON.format(name=_NAMES[role], checks=listed) + "\n\n" + _FOCUS[role]


def critics_for(language: str) -> tuple[CriticRole, ...]:
    """The Persian language critic only judges Persian drafts."""

    return tuple(
        role
        for role in CriticRole
        if role is not CriticRole.PERSIAN_QUALITY or language == "fa"
    )


# ---------------------------------------------------------------------------
# Deterministic script integrity (TrueCrime language_quality gate)

_PERSIAN_ARABIC_LETTER = re.compile(
    r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]"
)
_LATIN_WORD = re.compile(r"\b[A-Za-z][A-Za-z'\-]+\b")

SCRIPT_GATES: dict[str, tuple[float, float]] = {
    # language: (minimum share of target-script letters, max Latin-word share)
    "fa": (0.90, 0.03),
    "ar": (0.90, 0.03),
}


@dataclass(frozen=True)
class ScriptIntegrity:
    script_ratio: float
    foreign_word_ratio: float
    passed: bool


def script_integrity(text: str, language: str) -> ScriptIntegrity | None:
    """Share of target-script letters and of Latin words; None when the
    language has no script gate (de, en)."""

    gate = SCRIPT_GATES.get(language)
    if gate is None:
        return None
    letters = [c for c in text if c.isalpha()]
    target = _PERSIAN_ARABIC_LETTER.findall(text)
    script_ratio = len(target) / len(letters) if letters else 0.0
    words = text.split()
    foreign = _LATIN_WORD.findall(text)
    foreign_ratio = len(foreign) / len(words) if words else 0.0
    return ScriptIntegrity(
        script_ratio=round(script_ratio, 4),
        foreign_word_ratio=round(foreign_ratio, 4),
        passed=script_ratio >= gate[0] and foreign_ratio <= gate[1],
    )
