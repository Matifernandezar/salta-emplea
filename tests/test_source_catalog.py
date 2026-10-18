"""El catálogo identifica fuentes; no inventa conexiones ni permisos."""

import pytest

from salta_emplea.source_catalog import select_preset, source_presets


def test_selected_sources_are_manual_disabled_and_unauthorized():
    presets = source_presets()
    assert isinstance(presets, tuple)
    assert {item['id'] for item in presets} == {
        'instagram-empleosalta12', 'computrabajo-salta', 'linkedin',
    }
    for item in presets:
        assert item['method'] == 'manual'
        assert item['status'] == 'disabled'
        assert item['automation_ready'] is False
        assert item['authorized'] is False
        assert item['enabled'] is False
        assert item['status_label'] and item['access_explanation']
        assert item['url'].startswith('https://')
        assert item['terms_url'].startswith('https://')


def test_changed_catalog_copy_cannot_authorize_or_replace_a_future_reference():
    presets = source_presets()
    instagram = presets[0]
    original = instagram.copy()
    instagram.update(authorized=True, enabled=True, url='https://prueba.invalid/')
    assert source_presets()[0] == original
    assert select_preset(original['id']) == original


def test_selected_copy_cannot_change_global_source_configuration():
    preset = select_preset('linkedin')
    preset['method'] = 'jobicy'
    preset['authorized'] = True
    assert select_preset('linkedin')['method'] == 'manual'
    assert select_preset('linkedin')['authorized'] is False


@pytest.mark.parametrize('unknown', ['', 'jobicy', 'https://www.linkedin.com/jobs/',
                                     '../linkedin', None, {'id': 'linkedin'}])
def test_unknown_presets_fail_closed(unknown):
    with pytest.raises(ValueError, match='Fuente elegida desconocida'):
        select_preset(unknown)


def test_references_preserve_user_selected_account_and_local_portal_scope():
    assert select_preset('instagram-empleosalta12')['url'] == (
        'https://www.instagram.com/empleosalta12/'
    )
    assert select_preset('computrabajo-salta')['url'] == (
        'https://ar.computrabajo.com/trabajo-en-salta'
    )
    assert 'otra persona' in select_preset('instagram-empleosalta12')['access_explanation']
