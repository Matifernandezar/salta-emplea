"""Navegación y búsqueda con inventario PRUEBA aislado, sin proveedores."""

from contextlib import contextmanager
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlsplit

from flask import template_rendered
import pytest

from salta_emplea import db, domain, homepage
from salta_emplea.app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app({
        'TESTING': True, 'APP_ENV': 'development', 'SERVERLESS': False,
        'SECRET_KEY': 'PRUEBA-clave-aislada-de-portada',
        'DATABASE_URL': '', 'DATABASE_PATH': str(tmp_path / 'PRUEBA.sqlite3'),
        'UPLOAD_DIR': str(tmp_path / 'imagenes-PRUEBA'),
        'PUBLIC_BASE_URL': 'https://example.test',
        'RESEND_API_KEY': '', 'MAIL_FROM': '', 'OCR_ENABLED': '0',
    })


@pytest.fixture
def conn(app):
    connection = db.connect(app.config['DATABASE_TARGET'])
    yield connection
    connection.close()


def make_offer(conn, *, approved=True, **changes):
    number = conn.execute('SELECT count(*) FROM jobs').fetchone()[0] + 1
    data = {
        'title': f'PRUEBA — Auxiliar {number}',
        'company': 'Empresa ficticia de pruebas', 'location': 'Orán',
        'modality': 'presencial', 'sector': 'Administración',
        'schedule': 'Jornada completa',
        'description': f'Contenido ficticio de PRUEBA, caso {number}.',
        'requirements': 'Solo datos informados en la fuente de PRUEBA.',
        'source_url': f'https://example.test/PRUEBA/{number}',
        'application_url': f'https://example.test/PRUEBA/postular/{number}',
        'original_text': f'Original de PRUEBA {number}; no representa una vacante.',
    }
    data.update(changes)
    job_id, _ = domain.create_job(conn, data, actor='administrador')
    if approved:
        domain.transition_job(conn, job_id, 'approve', 'administrador', acknowledge=True)
    return job_id


@contextmanager
def rendered(app):
    contexts = []

    def capture(sender, template, context, **_extra):
        contexts.append(context)

    template_rendered.connect(capture, app)
    try:
        yield contexts
    finally:
        template_rendered.disconnect(capture, app)


def test_public_search_includes_rubro_and_tolerates_accents(conn):
    selected = make_offer(conn, location='Orán', sector='Tecnología',
                          modality='híbrida', schedule='Media jornada')
    make_offer(conn, location='Cafayate', sector='Comercio')
    assert [job['id'] for job in domain.public_jobs(conn, {
        'q': 'tecnologia', 'location': 'ORAN', 'sector': 'tecnologia',
        'modality': 'hibrida', 'schedule': 'MEDIA JORNADA',
    })] == [selected]
    assert domain.public_jobs(conn, {'q': "' OR 1=1 --"}) == []


def test_literal_sql_wildcards_in_sector_search(conn):
    selected = make_offer(conn, sector='PRUEBA 100%_literal')
    make_offer(conn, sector='PRUEBA 100 por ciento')
    assert [job['id'] for job in domain.public_jobs(conn, {'q': '%_'})] == [selected]


def test_remove_one_filter_preserves_the_other_selections_and_anchor():
    filters = {
        'q': '<script>alert("PRUEBA")</script>', 'location': 'Orán',
        'sector': 'Tecnología', 'modality': 'híbrida',
        'schedule': 'Media jornada', 'days': '7',
    }
    model = homepage.presentation([], [], filters)
    assert len(model['active_filters']) == len(filters)
    for removed, chip in zip(homepage.FILTER_KEYS, model['active_filters']):
        parsed = urlsplit(chip['url'])
        assert not parsed.scheme and not parsed.netloc and parsed.path == '/'
        assert parsed.fragment == 'ofertas'
        assert parse_qs(parsed.query) == {key: [value] for key, value in filters.items()
                                         if key != removed}
        assert '<script>' not in chip['url']


def test_search_filters_keep_legacy_date_and_remove_unrelated_parameters():
    assert homepage.search_filters({
        'q': '  técnico  ', 'location': '', 'date_days': '7',
        'utm_source': 'PRUEBA', 'next': 'https://evil.example',
    }) == {'q': 'técnico', 'days': '7'}
    assert homepage.search_filters({'days': '1', 'date_days': '7'}) == {'days': '1'}
    assert homepage.search_filters({'q': '   ', 'utm_source': 'PRUEBA'}) == {}


@pytest.mark.parametrize('value', ['hibrida', 'HÍBRIDA', '  híbrida  '])
def test_known_modalities_normalize_without_guessing(value):
    assert homepage.search_filters({'modality': value}) == {'modality': 'híbrida'}
    assert homepage.search_filters({'modality': 'PRUEBA desconocida'}) == {
        'modality': 'PRUEBA desconocida'}


@pytest.mark.parametrize('value,expected', [('07', '7'), ('+02', '2'), ('3650', '3650'),
                                          ('ayer', 'ayer'), ('0', '0'), ('3651', '3651')])
def test_dates_normalize_only_valid_integer_ranges(value, expected):
    assert homepage.search_filters({'days': value}) == {'days': expected}


def test_modality_and_date_render_the_matching_selection_after_roundtrip(app, conn):
    make_offer(conn, modality='híbrida', sector='Tecnología')
    class Selected(HTMLParser):
        def __init__(self, html):
            super().__init__()
            self.current = None
            self.selected = {}
            self.feed(html)

        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'select':
                self.current = attrs.get('name')
            elif tag == 'option' and self.current and 'selected' in attrs:
                self.selected[self.current] = attrs.get('value')

        def handle_endtag(self, tag):
            if tag == 'select':
                self.current = None

    with rendered(app) as contexts:
        response = app.test_client().get('/?modality=hibrida&days=07&location=oran')
    assert response.status_code == 200
    assert len(contexts[0]['jobs']) == 1
    assert contexts[0]['filters'] == {'location': 'oran', 'modality': 'híbrida', 'days': '7'}
    selection = Selected(response.get_data(as_text=True)).selected
    assert selection['modality'] == 'híbrida'
    assert selection['days'] == '7'
    assert selection['location'] == 'oran'  # no se inventó Capital u otra localidad


def test_custom_valid_days_and_unknown_modality_survive_request(app):
    with rendered(app) as contexts:
        response = app.test_client().get('/?modality=PRUEBA-desconocida&days=02')
    assert response.status_code == 200
    assert contexts[0]['filters'] == {'modality': 'PRUEBA-desconocida', 'days': '2'}
    assert contexts[0]['jobs'] == []


def test_chip_url_whitelist_and_internal_length_limit():
    result = homepage.presentation([], [], {'q': 'PRUEBA', 'next': 'https://evil.example'})
    assert result['active_filters'] == [{'label': 'Búsqueda: PRUEBA', 'url': '/#ofertas'}]
    with pytest.raises(ValueError, match='200 caracteres'):
        homepage.presentation([], [], {'q': 'PRUEBA', 'location': 'á' * 201})
    # El límite corresponde al valor, sin truncar caracteres al codificar.
    valid = homepage.presentation([], [], {'q': 'á' * 200, 'sector': 'PRUEBA'})
    assert parse_qs(urlsplit(valid['active_filters'][1]['url']).query)['q'] == ['á' * 200]


def test_zero_results_keep_selected_value_in_facets(app, conn):
    make_offer(conn)
    with rendered(app) as contexts:
        response = app.test_client().get('/?location=PRUEBA+sin+inventario&sector=Otro&days=7')
    assert response.status_code == 200
    context = contexts[0]
    assert context['filters'] == {'location': 'PRUEBA sin inventario', 'sector': 'Otro', 'days': '7'}
    assert context['jobs'] == []
    assert 'PRUEBA sin inventario' in context['facets']['locations']
    assert 'Otro' in context['facets']['sectors']
    assert context['home']['is_filtered']
    assert context['home']['filtered_count'] == 0


def test_navigation_counts_only_approved_active_inventory(app, conn):
    active = make_offer(conn, location='Salta Capital', sector='Comercio')
    remote = make_offer(conn, location='Worldwide', modality='remota', sector='Tecnología')
    make_offer(conn, approved=False, location='Tartagal', sector='Pendiente')
    archived = make_offer(conn, location='Cerrillos', sector='Archivado')
    domain.transition_job(conn, archived, 'archive', 'administrador')
    expired = make_offer(conn, location='Cafayate', sector='Vencido')
    with conn:
        conn.execute("UPDATE jobs SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (expired,))
    with rendered(app) as contexts:
        response = app.test_client().get('/')
    assert response.status_code == 200
    context = contexts[0]
    model = context['home']
    assert {job['id'] for job in context['jobs']} == {active, remote}
    assert model['total_published'] == model['filtered_count'] == 2
    assert {link['label'] for link in model['sector_links']} == {'Comercio', 'Tecnología'}
    assert model['location_links'] == [{'label': 'Salta Capital', 'count': 1,
                                        'url': '/?location=Salta+Capital#ofertas'}]
    assert 'Worldwide' not in context['facets']['locations']
    assert all(link['count'] == 1 for link in model['sector_links'])


def test_shortcuts_never_infer_experience_or_remote_residence():
    jobs = [{'modality': 'remota', 'location': 'Worldwide', 'sector': 'Soporte',
             'schedule': 'Tiempo completo',
             'description': 'No admitimos postulantes sin experiencia. Global remote.'}]
    assert homepage.presentation(jobs, jobs, {})['shortcuts'] == []


def test_part_time_shortcut_requires_an_explicit_schedule():
    jobs = [{'schedule': 'Tiempo completo', 'description': 'Buscá medio tiempo'},
            {'schedule': 'Media jornada'}, {'schedule': 'Media jornada'}]
    model = homepage.presentation(jobs, jobs, {})
    assert model['shortcuts'] == [{'label': 'Medio tiempo', 'count': 2,
                                  'url': '/?schedule=Media+jornada#ofertas'}]
    assert homepage.presentation([{'schedule': None}], [], {})['shortcuts'] == []


def test_missing_optional_fields_do_not_create_empty_links():
    model = homepage.presentation([{'location': None, 'sector': None, 'schedule': None}], [], {})
    assert model['sector_links'] == model['location_links'] == model['shortcuts'] == []
    assert not model['is_filtered']


def test_preview_and_mail_flags_match_actual_configuration(app):
    with rendered(app) as contexts:
        response = app.test_client().get('/')
    assert response.status_code == 200
    assert contexts[0]['preview_mode'] is True
    assert contexts[0]['mail_available'] is False


def test_development_credentials_only_expose_an_inert_available_mail_route(app):
    app.config.update(RESEND_API_KEY='PRUEBA-no-real', MAIL_FROM='PRUEBA <prueba@example.test>')
    with rendered(app) as contexts:
        response = app.test_client().get('/')
    assert response.status_code == 200
    assert contexts[0]['mail_available'] is True
    assert app.config['APP_ENV'] == 'development'


def test_preview_flag_never_leaks_into_production(tmp_path):
    application = create_app({
        'TESTING': True, 'APP_ENV': 'production', 'SERVERLESS': False,
        'SECRET_KEY': 'PRUEBA-clave-larga-exclusiva-de-produccion-aislada',
        'ADMIN_PASSWORD_HASH': 'PRUEBA-hash-ficticio-no-usado-para-ingresar',
        'DATABASE_URL': '', 'DATABASE_PATH': str(tmp_path / 'PRUEBA-produccion.sqlite3'),
        'UPLOAD_DIR': str(tmp_path / 'PRUEBA-imagenes'),
        'PUBLIC_BASE_URL': 'https://example.test',
        'PUBLIC_RESPONSIBLE_NAME': 'PRUEBA', 'PUBLIC_CONTACT_EMAIL': '',
        'PUBLIC_CONTACT_URL': '', 'RESEND_API_KEY': '', 'MAIL_FROM': '',
    })
    with rendered(application) as contexts:
        response = application.test_client().get('/')
    assert response.status_code == 200
    assert contexts[0]['preview_mode'] is False
    assert contexts[0]['mail_available'] is False


def test_invalid_dates_remain_a_clear_client_error(app):
    assert app.test_client().get('/?days=ayer').status_code == 400
