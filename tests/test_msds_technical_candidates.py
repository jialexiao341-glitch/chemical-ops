from scripts.msds_technical_candidates import make_candidate


def test_candidates_are_verbatim_and_keep_source_coordinates():
    source = {
        'source': {'filename': 's.docx', 'sha256': 'abc'},
        'source_table': 3, 'source_heading': '表1-003 示例',
        'name_from_heading': '示例', 'cas_candidate': '64-17-5', 'cas_valid_checksum': True,
        'rows': [
            {'row': 1, 'cells': ['标识', '中文名：示例', '危规号：123']},
            {'row': 2, 'cells': ['理化性质', '沸点（℃）：78.3', '密度：']},
            {'row': 3, 'cells': ['燃烧爆炸危险性', '危险特性：易燃']},
        ],
    }
    candidate = make_candidate(source)
    assert candidate['status'] == 'DRAFT' and not candidate['published']
    assert candidate['source_type'] == 'msds'
    assert candidate['specifications'] == []
    assert candidate['identity_review_required'] is True
    assert [(x['section'], x['text'], x['source_row'], x['source_cell']) for x in candidate['items']] == [
        ('产品标识', '中文名：示例', 1, 2),
        ('理化性质', '沸点（℃）：78.3', 2, 2),
    ]


def test_missing_cas_is_not_inferred_and_other_categories_are_excluded():
    source = {'source': {'filename': 's.docx', 'sha256': 'abc'}, 'source_table': 1,
              'source_heading': '表1-001 混合物', 'name_from_heading': '混合物',
              'cas_candidate': None, 'cas_valid_checksum': None,
              'rows': [{'row': 1, 'cells': ['防护', '佩戴手套']}]}
    result = make_candidate(source)
    assert result['cas_candidate'] is None
    assert result['items'] == []


def test_seven_categories_include_combustion_storage_and_unlabelled_usage():
    source = {'source': {'filename': 's.docx', 'sha256': 'abc'}, 'source_table': 2,
              'source_heading': '表1-002 示例', 'name_from_heading': '示例',
              'cas_candidate': None, 'cas_valid_checksum': None,
              'rows': [
                  {'row': 1, 'cells': ['标识', '商品名：测试', '分子式：H2O']},
                  {'row': 2, 'cells': ['理化性质', '性状：液体', '溶解性：溶于水']},
                  {'row': 3, 'cells': ['燃烧爆炸危险性', '闪点（℃）：无意义', '稳定性：稳定']},
                  {'row': 4, 'cells': ['贮运', '包装方法：桶装\n储运条件：阴凉']},
                  {'row': 5, 'cells': ['用途', '用于制造材料。']},
              ]}
    result = make_candidate(source)
    assert [x['section'] for x in result['items']] == ['产品标识', '分子信息', '外观与溶解性',
        '外观与溶解性', '燃烧相关性质', '储存与包装信息', '用途']
    assert result['items'][4]['text'] == '闪点（℃）：无意义'
    assert result['items'][5]['text'] == '包装方法：桶装\n储运条件：阴凉'
    assert result['source']['table'] == 2
