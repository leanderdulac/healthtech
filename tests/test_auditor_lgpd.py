"""O auditor de LGPD/ISO não declara certificação e cobre o Anexo A inteiro."""

from datetime import date

from src.ops.lgpd_auditor import (
    STATUS_EVIDENCED,
    STATUS_GAP,
    all_controls,
    collect_probes,
    evaluate,
    render_report,
    write_report,
)


def _iso(controls):
    return [item for item in controls if item.framework.startswith("ISO/IEC 27001")]


def test_annex_a_has_the_93_controls():
    iso = _iso(all_controls())
    assert len(iso) == 93
    assert len({item.control_id for item in iso}) == 93
    themes = {item.control_id.split(".")[0] for item in iso}
    assert themes == {"5", "6", "7", "8"}
    assert sum(item.control_id.startswith("5.") for item in iso) == 37
    assert sum(item.control_id.startswith("6.") for item in iso) == 8
    assert sum(item.control_id.startswith("7.") for item in iso) == 14
    assert sum(item.control_id.startswith("8.") for item in iso) == 34


def test_report_states_gaps_and_refuses_certification():
    from src.ops.lgpd_auditor import ROOT

    text = render_report(ROOT, date(2026, 9, 28))
    assert "não é certificação" in text
    assert "não é parecer jurídico" in text
    assert "certificação obtida" not in text
    assert "está certificada" not in text
    assert "Art. 11" in text
    assert "Art. 48" in text
    assert "A.5.1" in text
    assert "A.8.34" in text
    assert "PIMS-01" in text
    assert "F-03" in text
    assert "F-06" in text
    assert "F-01" not in text
    assert "ht_admin_test_key" not in text
    assert "us-central1" in text


def test_known_controls_match_the_code():
    from src.ops.lgpd_auditor import ROOT

    probes = collect_probes(ROOT)
    by_id = {item.control_id: item for item in all_controls()}
    assert probes["purge_endpoint"].ok
    assert probes["purge_durable"].ok
    assert probes["hmac_auth"].ok
    assert probes["consent_ui"].ok is True
    assert probes["incident_procedure"].ok is True
    assert probes["legal_basis"].ok is True
    assert probes["transfer_mechanism"].ok is False
    assert probes["dpo"].ok is False
    assert evaluate(by_id["8.5"], probes) == STATUS_EVIDENCED
    assert evaluate(by_id["Art. 48"], probes) == STATUS_EVIDENCED
    assert evaluate(by_id["7.1"], probes) != STATUS_EVIDENCED
    assert evaluate(by_id["Art. 11"], probes) == STATUS_EVIDENCED
    assert evaluate(by_id["Art. 33"], probes) == STATUS_GAP


def test_write_report_lands_in_auditor_folder(tmp_path):
    target = write_report(tmp_path, date(2026, 9, 28))
    assert target.name == "auditoria-lgpd-iso-2026-09-28.md"
    assert target.parent.name == "relatorios"
    body = target.read_text(encoding="utf-8")
    assert "Auditoria interna" in body or "auditoria interna" in body
    assert STATUS_GAP in body
