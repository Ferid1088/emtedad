"""Deterministic parsing of the explicit Manasek booklet structure."""

import re
from dataclasses import dataclass

from app.core.ayin.normalization import digits_to_ascii, normalize_persian_text
from app.ritual.domain import GATE_ORDER, CueType, GateKey, RitualPieceType
from app.ritual.extractor import RitualPdfExtraction

_PIECE = re.compile(
    r"^(?P<title>.+):\s*(?P<gate>خاک|آب|آتش|باد|کشش)-\s*"
    r"(?P<number>\d+)\s*قطعٔه$"
)
_RETURN = re.compile(r"^مرور مرحلٔه\s+(?P<title>.+)-\s*(?P<number>[1-7])\s*بازگشت$")
_RANGE = re.compile(
    r"(?P<sm>\d{1,2}):(?P<ss>\d{2}).*?[-–].*?(?P<em>\d{1,2}):(?P<es>\d{2})"
)
_POINT = re.compile(r"(?P<m>\d{1,2}):(?P<s>\d{2})")

_GATE_BY_FA = {
    "خاک": GateKey.EARTH,
    "آب": GateKey.WATER,
    "آتش": GateKey.FIRE,
    "باد": GateKey.WIND,
    "کشش": GateKey.PULL,
}


@dataclass(frozen=True)
class SourceLine:
    page: int
    text: str


@dataclass(frozen=True)
class ParsedCue:
    page: int
    sequence: int
    cue_type: CueType
    start_seconds: int | None
    end_seconds: int | None
    text: str
    optional: bool


@dataclass(frozen=True)
class ParsedMusic:
    page: int
    duration_seconds: int
    sonic_family: str
    emotional_arc: str
    intensity_profile: str
    prohibited_features: tuple[str, ...]
    transition_requirements: str
    ending_requirements: str
    original_prompt: str


@dataclass(frozen=True)
class ParsedRitual:
    stable_key: str
    page: int
    title: str
    purpose: str
    instructions: str
    duration_seconds: int
    piece_type: RitualPieceType
    stage_position: int | None
    gate: GateKey | None
    cues: tuple[ParsedCue, ...]
    music: ParsedMusic


@dataclass(frozen=True)
class ParsedManasek:
    rituals: tuple[ParsedRitual, ...]


class ManasekStructureError(RuntimeError):
    """Raised when the explicit 35+7+collective structure is not recoverable."""


def parse_manasek(extraction: RitualPdfExtraction) -> ParsedManasek:
    """Parse only explicit source headings, cue timings, and music prompts."""

    lines = _source_lines(extraction)
    boundaries: list[tuple[int, RitualPieceType, re.Match[str]]] = []
    for index, line in enumerate(lines):
        piece_match = _PIECE.match(line.text)
        return_match = _RETURN.match(line.text)
        if piece_match:
            boundaries.append((index, RitualPieceType.GATE, piece_match))
        elif return_match:
            boundaries.append((index, RitualPieceType.RETURN, return_match))
    collective_start = next(
        index
        for index, line in enumerate(lines)
        if line.text == "مناسک جمعی -معماری مستقل"
    )

    rituals: list[ParsedRitual] = []
    for boundary_index, (start, piece_type, match) in enumerate(boundaries):
        end = (
            boundaries[boundary_index + 1][0]
            if boundary_index + 1 < len(boundaries)
            else collective_start
        )
        segment = lines[start:end]
        if piece_type is RitualPieceType.GATE:
            piece_number = int(match.group("number"))
            stage_position = ((piece_number - 1) // 5) + 1
            gate = _GATE_BY_FA[match.group("gate")]
            stable_key = f"individual-stage-{stage_position}-{gate.value.lower()}"
        else:
            stage_position = int(match.group("number"))
            gate = None
            stable_key = f"individual-stage-{stage_position}-return"
        rituals.append(
            _parse_segment(
                segment,
                stable_key=stable_key,
                title=match.group("title").strip(),
                piece_type=piece_type,
                stage_position=stage_position,
                gate=gate,
                duration_seconds=600,
            )
        )

    rituals.append(_parse_collective(lines))
    gate_pieces = [item for item in rituals if item.piece_type is RitualPieceType.GATE]
    returns = [item for item in rituals if item.piece_type is RitualPieceType.RETURN]
    if len(gate_pieces) != 35 or len(returns) != 7:
        raise ManasekStructureError(
            "expected 35 gate pieces and 7 Returns; found "
            f"{len(gate_pieces)} and {len(returns)}"
        )
    for stage in range(1, 8):
        gates = [item.gate for item in gate_pieces if item.stage_position == stage]
        if gates != list(GATE_ORDER):
            raise ManasekStructureError(
                f"stage {stage} does not preserve five-gate order"
            )
    return ParsedManasek(rituals=tuple(rituals))


def _source_lines(extraction: RitualPdfExtraction) -> list[SourceLine]:
    return [
        SourceLine(page_number, digits_to_ascii(normalize_persian_text(raw_line)))
        for page_number, page in enumerate(extraction.raw_pages, start=1)
        for raw_line in page.splitlines()
        if normalize_persian_text(raw_line)
    ]


def _parse_segment(
    segment: list[SourceLine],
    *,
    stable_key: str,
    title: str,
    piece_type: RitualPieceType,
    stage_position: int,
    gate: GateKey | None,
    duration_seconds: int,
) -> ParsedRitual:
    if not segment:
        raise ManasekStructureError(f"empty source segment for {stable_key}")
    purpose = _field(segment, "کارکرد")
    instructions = _field(segment, "راهنمای تجربه")
    music_marker = next(
        index
        for index, line in enumerate(segment)
        if "پرامپت دقیق ساخت موسیقی" in line.text
    )
    cue_source = segment[:music_marker]
    cue_lines = [line for line in cue_source if _RANGE.search(line.text)]
    if piece_type is RitualPieceType.RETURN:
        cue_lines = [
            line
            for line in cue_source
            if _POINT.search(line.text) and "timing:" not in line.text.lower()
        ][:6]
    cues = tuple(
        _cue(line, sequence=index, point_only=piece_type is RitualPieceType.RETURN)
        for index, line in enumerate(cue_lines[:6], start=1)
    )
    if len(cues) < 5:
        raise ManasekStructureError(f"too few timed cues for {stable_key}")
    music = _music(segment, duration_seconds)
    return ParsedRitual(
        stable_key=stable_key,
        page=segment[0].page,
        title=title,
        purpose=purpose,
        instructions=instructions or purpose,
        duration_seconds=duration_seconds,
        piece_type=piece_type,
        stage_position=stage_position,
        gate=gate,
        cues=cues,
        music=music,
    )


def _field(segment: list[SourceLine], marker: str) -> str:
    for line in segment:
        if marker in line.text:
            return (
                line.text.replace(f":{marker}", "")
                .replace(f"{marker}:", "")
                .strip(" .")
            )
    return ""


def _cue(line: SourceLine, *, sequence: int, point_only: bool) -> ParsedCue:
    range_match = None if point_only else _RANGE.search(line.text)
    if range_match:
        start = int(range_match.group("sm")) * 60 + int(range_match.group("ss"))
        end = int(range_match.group("em")) * 60 + int(range_match.group("es"))
        text = _RANGE.sub("", line.text).strip(" .—-")
    else:
        point = _POINT.search(line.text)
        if point is None:
            raise ManasekStructureError(f"cue has no timestamp: {line.text}")
        start = int(point.group("m")) * 60 + int(point.group("s"))
        end = None
        text = _POINT.sub("", line.text, count=1).strip(" .—-")
    return ParsedCue(
        page=line.page,
        sequence=sequence,
        cue_type=CueType.WHISPER,
        start_seconds=start,
        end_seconds=end,
        text=text,
        optional=True,
    )


def _music(segment: list[SourceLine], duration_seconds: int) -> ParsedMusic:
    marker_index = next(
        (
            index
            for index, line in enumerate(segment)
            if "پرامپت دقیق ساخت موسیقی" in line.text
        ),
        None,
    )
    if marker_index is None:
        raise ManasekStructureError(f"music prompt missing near page {segment[0].page}")
    prompt_lines = segment[marker_index + 1 :]
    prompt = " ".join(line.text for line in prompt_lines).strip()
    if not prompt:
        raise ManasekStructureError(f"music prompt empty near page {segment[0].page}")
    sonic_family = _english_field(prompt, "Sonic family:", "Emotional/structural arc:")
    emotional_arc = _english_field(
        prompt, "Emotional/structural arc:", "Narration is recorded"
    )
    if "Sonic family:" not in prompt and "Earth =" in prompt:
        # Return prompts encode the five gate motifs directly instead of using
        # the otherwise consistent ``Sonic family`` label.
        motif_tail = prompt.split("Earth =", 1)[1]
        transition_marker = "Do not make a medley"
        sonic_family = "Earth = " + motif_tail.split(transition_marker, 1)[0].strip(
            " ."
        )
        emotional_arc = transition_marker + motif_tail.split(transition_marker, 1)[
            1
        ].split("Narration is separate", 1)[0].strip(" .")
    return ParsedMusic(
        page=prompt_lines[0].page if prompt_lines else segment[0].page,
        duration_seconds=duration_seconds,
        sonic_family=sonic_family,
        emotional_arc=emotional_arc,
        intensity_profile=(
            "Choice-preserving controlled intensity with a required safe descent."
        ),
        prohibited_features=tuple(
            item.strip(" .")
            for item in _english_field(prompt, "Avoid:", "End in a way").split(",")
            if item.strip()
        ),
        transition_requirements=(
            "Narration windows remain low-density; transitions preserve voluntary exit."
        ),
        ending_requirements=_ending(prompt),
        original_prompt=prompt,
    )


def _english_field(value: str, start: str, end: str) -> str:
    if start not in value:
        return "Source does not isolate this field; retain original prompt for review."
    tail = value.split(start, 1)[1]
    return tail.split(end, 1)[0].strip(" .") if end in tail else tail.strip(" .")


def _ending(prompt: str) -> str:
    marker = "End in a way"
    if marker in prompt:
        return marker + prompt.split(marker, 1)[1].strip()
    if "final minute" in prompt:
        return "Final minute returns to simple room-like warmth."
    return "Return to ordinary orientation without a completion claim."


def _parse_collective(lines: list[SourceLine]) -> ParsedRitual:
    start = next(
        index
        for index, line in enumerate(lines)
        if line.text == "مناسک جمعی -معماری مستقل"
    )
    segment = lines[start:]
    timeline = [
        line
        for line in segment
        if line.text.startswith("•") and _RANGE.search(line.text)
    ]
    cues = tuple(
        _cue(line, sequence=index, point_only=False)
        for index, line in enumerate(timeline[:7], start=1)
    )
    prompt_marker = next(
        index
        for index, line in enumerate(segment)
        if "پرامپت دقیق موسیقی جمعی" in line.text
    )
    prompt_lines: list[SourceLine] = []
    for line in segment[prompt_marker + 1 :]:
        if line.text == "نسخٔه آنلاین مناسک جمعی":
            break
        prompt_lines.append(line)
    prompt = " ".join(line.text for line in prompt_lines)
    music = ParsedMusic(
        page=40,
        duration_seconds=1440,
        sonic_family="Five distinct gate motifs in one shared acoustic field.",
        emotional_arc=(
            "Grounded arrival, safe Fire peak, descent, relation, ordinary return."
        ),
        intensity_profile=(
            "Strong but bounded; optional movement and clear exit from Fire."
        ),
        prohibited_features=(
            "coercion",
            "panic-inducing dynamics",
            "militarism",
            "forced ecstasy",
            "romantic manipulation",
            "sacred-frequency claims",
        ),
        transition_requirements="Low-density narration at every gate transition.",
        ending_requirements="Final minute returns to simple room-like warmth.",
        original_prompt=prompt,
    )
    return ParsedRitual(
        stable_key="collective-horizontal-emtedad",
        page=40,
        title="مناسک جمعی - معماری مستقل",
        purpose="میدان مشترک توجه با حفظ یگانگی و امکان امتداد افقی",
        instructions="حلقه یا نیم دایره؛ لمس، نگاه و دست گرفتن فقط با رضایت روشن.",
        duration_seconds=1440,
        piece_type=RitualPieceType.COLLECTIVE,
        stage_position=None,
        gate=None,
        cues=cues,
        music=music,
    )
