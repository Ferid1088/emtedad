"""Native-language realization instructions shared by localization paths."""

from app.lecture.domain import PublicationLanguage


def native_realization_instruction(language: PublicationLanguage) -> str:
    language_name = {
        PublicationLanguage.FA: "Persian",
        PublicationLanguage.DE: "German",
        PublicationLanguage.EN: "English",
        PublicationLanguage.AR: "Modern Standard Arabic",
    }[language]
    return f"""
Create an original, publication-quality spoken lecture in {language_name}.
The approved source is semantic material, not a sentence-by-sentence script.
Do NOT preserve Persian sentence structure, paragraph rhythm, clause order, or
literal phrasing. Reconstruct the prose natively for the target language's
educated listener, with natural idiom, rhythm, transitions, sentence length,
and emotional movement. Transfer meaning, conceptual distinctions, epistemic
status, examples, argumentative movement, and open questions—not syntax.

For Persian, use contemporary Iranian Persian that sounds originally Persian,
with varied rhythm, speakable sentences, and restrained literary elegance.
Avoid translated-academic patterns and unnecessary repetition of formulas such
as «در چارچوب»، «به این معنا که»، «ممکن است»، «از سوی دیگر»، and «این بدان
معنا نیست که» unless genuinely natural.
For German, write original educated spoken German without bureaucratic
nominalization. For English, write original thoughtful spoken English. For
Arabic, write natural high-register spoken Modern Standard Arabic without
literal Persian syntax or forced archaism.

Do not over-explain every distinction as repeated "X is not Y" formulas; use
precision where needed, then return to human experience. Do not add facts,
strengthen certainty, resolve open questions, lose non-equivalence, or change
Ayin terminology. Validate the native rewriting afterward against the approved
source, Semantic Master, claim identities, uncertainty, open questions, and
terminology. Return only the target-language realization.
""".strip()
