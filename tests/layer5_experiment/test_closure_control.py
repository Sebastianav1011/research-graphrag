import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('closure_control',Path(__file__).resolve().parents[2]/'scripts/run_layer4_closure.py')
control=importlib.util.module_from_spec(spec);spec.loader.exec_module(control)


def plan():return {'projects':[{'project':{'project_id':str(i)}} for i in range(20)]}


def test_pilot_scope_does_not_accept_remaining_projects():
    control.validate_execution_scope('pilot',plan(),'.',{'project_ids':list(map(str,range(5)))})
    with pytest.raises(ValueError):control.validate_execution_scope('pilot',plan(),'.',{'project_ids':list(map(str,range(20)))})
    with pytest.raises(ValueError):control.validate_execution_scope('pilot',plan(),'.',{'project_ids':['0']*5})


def test_continuation_rejects_pilot_scope_before_any_call():
    with pytest.raises(ValueError,match='only pending'):
        control.validate_execution_scope('remaining',plan(),'.',{'project_ids':['0']})


def test_current_settings_keep_original_run_configuration():
    value=control.settings()
    assert value['base_config']=='config/layer4_final.yaml'
    assert value['fallback']['max_additional']==2
    assert control.legacy(control.ROOT, control.ROOT/value['closure_directory']).relative_to(control.ROOT).as_posix()=='outputs/layer4/pruebas/cierre_v2_20'
