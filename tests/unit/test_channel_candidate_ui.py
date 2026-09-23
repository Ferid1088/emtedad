from pathlib import Path


def test_channel_detail_has_select_all_and_live_import_controls() -> None:
    template = (
        Path(__file__).parents[2] / "app" / "web" / "templates" / "channel_detail.html"
    ).read_text(encoding="utf-8")
    assert 'id="select-all-candidates"' in template
    assert 'id="selected-candidate-count"' in template
    assert 'id="import-selected-candidates"' in template
    assert "master.indeterminate" in template
    assert "box.checked = master.checked" in template
    assert "importButton.disabled = selected === 0" in template
    assert "${selected} ausgewählte hinzufügen" in template
