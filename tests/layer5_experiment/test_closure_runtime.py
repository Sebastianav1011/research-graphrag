import pytest

from layer4_evaluation.indicators.closure_runtime import human_opinions, check_source_display


def data():
    machine = ['123','Synthetic','ABC-01 — Example','Leer texto completo','NOT_SUPPORTED','No documented action.']
    return [machine+[None,None]], {('123','ABC-01'):machine}


def test_agreement_never_becomes_a_semantic_label_or_acceptance():
    rows, expected = data(); rows[0][6:] = [5,'I agree with NOT_SUPPORTED.']
    result = human_opinions(rows,expected)
    assert result['rated_pairs']==1 and result['mean_agreement']==5
    assert result['opinions'][0]['codex_decision']=='NOT_SUPPORTED'
    assert result['semantic_human_labels'] is None
    assert result['classification_metrics'] is None
    assert result['academic_acceptance'] is False


@pytest.mark.parametrize('grade',[True,False,0,6,1.5,'5'])
def test_rejects_nonordinal_grades(grade):
    rows,expected=data();rows[0][6]=grade
    with pytest.raises(ValueError,match='Agreement'):human_opinions(rows,expected)


@pytest.mark.parametrize('column',range(6))
def test_does_not_allow_user_input_to_change_machine_data(column):
    rows,expected=data();rows[0]=list(rows[0]);rows[0][column]='tampered'
    with pytest.raises(ValueError):human_opinions(rows,expected)


def test_missing_duplicate_and_unrated_pairs():
    rows,expected=data()
    with pytest.raises(ValueError):human_opinions([],expected)
    with pytest.raises(ValueError):human_opinions(rows+rows,expected)
    result=human_opinions(rows,expected)
    assert result['rated_pairs']==0 and result['mean_agreement'] is None


def test_source_display_only_allows_excel_edge_whitespace_and_preserves_offsets():
    expected=[['123','Synthetic','Resumen',' Original words ','summary; [0,16)']]
    actual=[['123','Synthetic','Resumen','Original words','summary; [0,16)']]
    assert check_source_display(actual,expected)==1
    for column,value in [(0,'124'),(3,'Original  words'),(3,'Different words'),(4,'summary; [0,14)')]:
        changed=[list(actual[0])];changed[0][column]=value
        with pytest.raises(ValueError):check_source_display(changed,expected)
