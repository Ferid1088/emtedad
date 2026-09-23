from app.content_strategy.persian_prompt import MASTER_PERSIAN_WRITING_PROMPT


def test_master_persian_prompt_preserves_editorial_boundaries() -> None:
    assert "The path did not begin with us" in MASTER_PERSIAN_WRITING_PROMPT
    assert "پذیرش تسلیم نیست" in MASTER_PERSIAN_WRITING_PROMPT
    assert "Never write that science proves Ayin" in MASTER_PERSIAN_WRITING_PROMPT
    assert "Return only the" in MASTER_PERSIAN_WRITING_PROMPT
    assert "finished Persian editorial draft" in MASTER_PERSIAN_WRITING_PROMPT
    assert "Lesson Content Package is the complete AYIN CORE" in (
        MASTER_PERSIAN_WRITING_PROMPT
    )
    assert "Do not retrieve from" in MASTER_PERSIAN_WRITING_PROMPT
    assert "Published Script Archive" in MASTER_PERSIAN_WRITING_PROMPT
