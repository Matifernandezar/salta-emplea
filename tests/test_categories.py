"""Catálogo cerrado, compatibilidad de avisos y sugerencias de Claude."""
from html.parser import HTMLParser

from salta_emplea import categories, claude_extraction, domain, homepage
from test_homepage_backend import app, conn, make_offer


class CategoryOptions(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.active = False
        self.values = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'select':
            self.active = attrs.get('name') == 'sector'
        elif tag == 'option' and self.active and attrs.get('value'):
            self.values.append(attrs['value'])

    def handle_endtag(self, tag):
        if tag == 'select':
            self.active = False


def test_all_public_and_editorial_options_use_only_the_23_categories(app):
    app.config.update(MAIL_ENABLED='1', RESEND_API_KEY='PRUEBA-no-real', MAIL_FROM='PRUEBA <prueba@example.test>')
    client = app.test_client()
    with client.session_transaction() as state:
        state['admin'] = True
    for path in ('/', '/admin/nueva', '/publicar', '/alertas'):
        response = client.get(path)
        assert response.status_code == 200
        assert CategoryOptions(response.data.decode()).values == list(categories.CATEGORIES), path


def test_legacy_offers_are_filterable_without_rewriting_original_data(conn):
    technology = make_offer(conn, sector='Tecnología')
    other = make_offer(conn, sector='Rubro anterior sin equivalencia')
    assert [j['id'] for j in domain.public_jobs(conn, {'sector': 'Informática / Telecomunicaciones'})] == [technology]
    assert [j['id'] for j in domain.public_jobs(conn, {'sector': 'tecnologia'})] == [technology]
    assert [j['id'] for j in domain.public_jobs(conn, {'sector': 'Otros'})] == [other]
    assert domain.public_jobs(conn, {'sector': 'categoria inventada'}) == []
    assert domain.public_job(conn, technology)['sector'] == 'Informática / Telecomunicaciones'
    assert conn.execute('SELECT sector FROM jobs WHERE id=?', (technology,)).fetchone()[0] == 'Tecnología'
    assert homepage.facets([], {'sector': 'categoria inventada'})['sectors'] == list(categories.CATEGORIES)


def test_admin_saves_only_a_catalog_category(app, conn):
    client = app.test_client()
    with client.session_transaction() as state:
        state['admin'], state['csrf'] = True, 'PRUEBA'
    result = client.post('/admin/nueva', data={'csrf_token': 'PRUEBA', 'title': 'PRUEBA — Puesto',
                                            'sector': 'Categoría que no existe'})
    assert result.status_code == 302
    assert conn.execute('SELECT sector FROM jobs').fetchone()[0] == 'Otros'


def test_claude_category_is_editorial_but_requires_literal_evidence():
    raw = {'text': 'Buscamos vendedor', 'fields': {
        'sector': {'value': 'Ventas', 'evidence': 'Buscamos vendedor'}}}
    result = claude_extraction._prepared(raw)['prepared']
    assert result['fields']['sector'] == 'Ventas'
    assert 'Categoría sugerida: revisar según el puesto' in result['uncertain_fields']
    raw['fields']['sector']['value'] = 'Categoría inventada'
    assert 'sector' not in claude_extraction._prepared(raw)['prepared']['fields']
    raw['fields']['sector'] = {'value': 'Ventas', 'evidence': 'dato inventado'}
    assert 'sector' not in claude_extraction._prepared(raw)['prepared']['fields']
