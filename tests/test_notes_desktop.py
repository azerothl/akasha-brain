import pytest

from akasha_brain.notes_desktop import decode_desktop


@pytest.mark.parametrize("packet,persisted", [(0x470F, False), (0x471F, True)])
def test_ocr_confirmation_preserves_the_independent_sqlite_verdict(packet, persisted):
    result = decode_desktop(packet)
    assert result["ocr_save_button_used"] and result["app_restarted"]
    assert result["ocr_note_selected_after_restart"] and result["ocr_content_visible"]
    assert result["sqlite_exact_row"] is persisted
