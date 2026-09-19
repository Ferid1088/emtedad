"""Reviewed Phase 3 identities and source-grounded safety policy."""

from dataclasses import dataclass

from app.ritual.domain import GateKey, SafetyCategory, SafetySeverity


@dataclass(frozen=True)
class GateSeed:
    key: GateKey
    title_fa: str
    role: str


@dataclass(frozen=True)
class StageSeed:
    key: str
    title_fa: str
    purpose: str


@dataclass(frozen=True)
class SafetySeed:
    key: str
    category: SafetyCategory
    severity: SafetySeverity
    requirement: str
    capability: str
    page: int
    prohibited_pattern: str | None = None


GATES: tuple[GateSeed, ...] = (
    GateSeed(GateKey.EARTH, "خاک", "تعین، مرز، جایگاه، این‌جا بودن و وزن"),
    GateSeed(GateKey.WATER, "آب", "تغییر، تبدیل، تداوم بدون تکرار و انعطاف"),
    GateSeed(GateKey.FIRE, "آتش", "فعلیت، نیرو، انتخاب، اثر و مسئولیت"),
    GateSeed(GateKey.WIND, "باد", "گذر، حرکت، انتقال و ناپایداری"),
    GateSeed(GateKey.PULL, "کشش", "نسبت، جهت، میل، فاصله، دیگری و رضایت"),
)

STAGES: tuple[StageSeed, ...] = (
    StageSeed("CONTACT", "تماس", "آشنایی مستقیم و ساده بدون ساختن نتیجه"),
    StageSeed("DISTINCTION", "تمایز", "دیدن فرق بن و صورت‌ها و نقش‌های گذرا"),
    StageSeed(
        "CONTINUITY_IN_CHANGE",
        "تداوم در تغییر",
        "نزدیک‌شدن به یگانگی در دل دگرگونی",
    ),
    StageSeed(
        "TEMPORAL_EMTEDAD",
        "امتداد زمانی",
        "دیدن حضور در پیش و پس، نه آغازشدن از خود",
    ),
    StageSeed(
        "EFFECT_AND_RESPONSIBILITY",
        "اثر و مسئولیت",
        "توجه به رد این بودن و آنچه ادامه یا متوقف می‌کند",
    ),
    StageSeed(
        "OTHER_AND_BREADTH_OF_PRESENCE",
        "دیگری و پهنای حضور",
        "نسبت با یگانگی‌های دیگر بدون ادغام یا تصاحب",
    ),
    StageSeed(
        "INTEGRATION",
        "یکپارچگی",
        "نگاه دوباره به پنج زاویه بدون اعلام کشف نهایی",
    ),
)


def _rule(
    key: str,
    category: SafetyCategory,
    requirement: str,
    *,
    capability: str | None = None,
    page: int = 3,
    severity: SafetySeverity = SafetySeverity.BLOCKING,
    prohibited: str | None = None,
) -> SafetySeed:
    return SafetySeed(
        key,
        category,
        severity,
        requirement,
        capability or key,
        page,
        prohibited,
    )


SAFETY_RULES: tuple[SafetySeed, ...] = (
    _rule("eyes_optional", SafetyCategory.CONSENT, "بستن چشم‌ها اختیاری است"),
    _rule("movement_optional", SafetyCategory.MOVEMENT, "حرکت اختیاری است"),
    _rule("touch_optional", SafetyCategory.TOUCH, "لمس اختیاری است"),
    _rule("speaking_optional", SafetyCategory.CONSENT, "حرف‌زدن اختیاری است"),
    _rule("writing_optional", SafetyCategory.CONSENT, "نوشتن اختیاری است"),
    _rule("sharing_optional", SafetyCategory.DISCLOSURE, "اشتراک‌گذاری اختیاری است"),
    _rule("gaze_optional", SafetyCategory.CONSENT, "نگاه مستقیم اختیاری است", page=40),
    _rule("may_stop", SafetyCategory.EXIT, "فرد هر لحظه می‌تواند توقف کند"),
    _rule("may_sit", SafetyCategory.EXIT, "نشستن پاسخ معتبر است"),
    _rule("may_open_eyes", SafetyCategory.EXIT, "بازکردن چشم‌ها پاسخ معتبر است"),
    _rule("may_reduce_sound", SafetyCategory.EXIT, "کم‌کردن صدا پاسخ معتبر است"),
    _rule("may_drink_water", SafetyCategory.EXIT, "نوشیدن آب پاسخ معتبر است"),
    _rule("may_leave", SafetyCategory.EXIT, "خروج کامل پاسخ معتبر است"),
    _rule("silence_valid", SafetyCategory.DISCLOSURE, "سکوت پاسخ معتبر است", page=42),
    _rule(
        "no_metaphysical_inference",
        SafetyCategory.INTERPRETATION,
        "راهنما از تجربه حقیقت متافیزیکی یا بن را نتیجه نمی‌گیرد",
    ),
    _rule(
        "no_diagnosis",
        SafetyCategory.MENTAL_HEALTH_BOUNDARY,
        "راهنما از پاسخ آیینی تشخیص روان‌شناختی نمی‌دهد",
    ),
    _rule(
        "no_required_experience",
        SafetyCategory.INTERPRETATION,
        "هیچ تجربه خاصی لازم نیست و هیچ‌چیز خاص نیز معتبر است",
        page=42,
    ),
    _rule(
        "intensity_not_truth",
        SafetyCategory.INTENSITY,
        "شدت تجربه معیار حقیقت نیست",
        page=42,
    ),
    _rule(
        "lack_of_intensity_not_failure",
        SafetyCategory.INTENSITY,
        "نبود شدت یا رخ‌ندادن تجربه خاص شکست نیست",
        page=42,
    ),
    _rule("no_forced_screaming", SafetyCategory.INTENSITY, "فریاد اجباری ممنوع است"),
    _rule("no_forced_catharsis", SafetyCategory.INTENSITY, "تخلیه اجباری ممنوع است"),
    _rule("no_breath_retention", SafetyCategory.BREATH, "حبس نفس ممنوع است"),
    _rule("no_hyperventilation", SafetyCategory.BREATH, "بیش‌تنفسی ممنوع است"),
    _rule(
        "no_group_pressure",
        SafetyCategory.GROUP_PRESSURE,
        "فشار جمعی و شکستن مقاومت ممنوع است",
    ),
    _rule("no_forced_touch", SafetyCategory.TOUCH, "لمس اجباری ممنوع است"),
    _rule("no_forced_intimacy", SafetyCategory.CONSENT, "صمیمیت اجباری ممنوع است"),
    _rule("no_forced_gaze", SafetyCategory.CONSENT, "نگاه اجباری ممنوع است"),
    _rule(
        "no_forced_disclosure",
        SafetyCategory.DISCLOSURE,
        "افشای تجربه اجباری ممنوع است",
    ),
    _rule(
        "no_sacred_frequency_claim",
        SafetyCategory.MUSIC,
        "ادعای فرکانس مقدس یا پنهان ممنوع است",
    ),
    _rule(
        "no_therapeutic_certainty",
        SafetyCategory.MUSIC,
        "موسیقی درمان قطعی یا اثر علمی تضمین‌شده نیست",
    ),
    _rule(
        "group_preserves_choice",
        SafetyCategory.GROUP_PRESSURE,
        "فعال‌شدن جمع انتخاب فرد را از بین نمی‌برد",
        page=40,
    ),
    _rule(
        "ordinary_reorientation",
        SafetyCategory.AFTERCARE,
        "شدت کاهش می‌یابد و فرد به زندگی روزمره بازمی‌گردد",
        page=41,
    ),
    _rule(
        "no_immediate_major_decision",
        SafetyCategory.AFTERCARE,
        "پس از تجربه شدید تصمیم بزرگ همان لحظه تشویق نمی‌شود",
        page=41,
        severity=SafetySeverity.WARNING,
    ),
)

REQUIRED_SAFETY_KEYS: frozenset[str] = frozenset(rule.key for rule in SAFETY_RULES)

GATE_CONCEPTS: dict[GateKey, tuple[str, ...]] = {
    GateKey.EARTH: ("bon",),
    GateKey.WATER: ("change", "emtedad"),
    GateKey.FIRE: ("ethics_of_majal",),
    GateKey.WIND: ("emtedad",),
    GateKey.PULL: ("other", "between", "direction"),
}

STAGE_CONCEPTS: dict[int, tuple[str, ...]] = {
    1: ("awareness",),
    2: ("bon", "pattern"),
    3: ("change", "emtedad"),
    4: ("emtedad",),
    5: ("ethics_of_majal",),
    6: ("other", "between"),
    7: ("bon", "emtedad"),
}
