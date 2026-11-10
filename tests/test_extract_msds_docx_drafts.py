from docx import Document

from scripts.extract_msds_docx_drafts import extract, valid_cas


def test_extraction_preserves_original_rows_and_requires_review(tmp_path):
    doc = Document()
    doc.add_heading('表1－001 乙醇', level=3)
    table = doc.add_table(rows=1, cols=2)
    table.cell(0, 0).text = '标识'
    table.cell(0, 1).text = 'CAS号：64－17－5'
    source = tmp_path / 'source.docx'
    doc.save(source)
    result = extract(source)
    record = result['records'][0]
    assert (record['source_heading'], record['name_from_heading']) == ('表1－001 乙醇', '乙醇')
    assert record['rows'] == [{'row': 1, 'cells': ['标识', 'CAS号：64－17－5']}]
    assert record['cas_raw'] == '64－17－5'
    assert record['cas_candidate'] == '64-17-5'
    assert record['cas_valid_checksum'] is True
    assert record['status'] == 'DRAFT' and record['published'] is False
    assert len(result['source']['sha256']) == 64


def test_cas_checksum_does_not_imply_identity():
    assert valid_cas('64-17-5')
    assert not valid_cas('133-74-0')
    assert not valid_cas('unknown')
