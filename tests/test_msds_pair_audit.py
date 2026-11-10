from scripts.audit_msds_pairs import audit


def test_audit_detects_missing_pairs_and_ambiguous_identity():
    msds = [
        {'file': 'one.json', 'name_from_heading': '甲', 'cas_candidate': '11-11-1', 'cas_valid_checksum': False},
        {'file': 'two.json', 'name_from_heading': '甲', 'cas_candidate': '11-11-1', 'cas_valid_checksum': False},
        {'file': 'three.json', 'name_from_heading': '乙', 'cas_candidate': None, 'cas_valid_checksum': None},
    ]
    tds = [
        {'msds_draft_file': 'one.json'},
        {'msds_draft_file': 'one.json'},
        {'msds_draft_file': 'extra.json'},
    ]
    result = audit(msds, tds)
    assert result['missing_pairs'] == ['three.json', 'two.json']
    assert result['duplicate_pairs'] == ['one.json']
    assert result['orphan_pairs'] == ['extra.json']
    assert result['duplicate_names'] == {'甲': ['one.json', 'two.json']}
    assert result['duplicate_cas'] == {'11-11-1': ['one.json', 'two.json']}
    assert result['missing_cas'] == ['three.json']
    assert result['invalid_cas'] == ['one.json', 'two.json']
