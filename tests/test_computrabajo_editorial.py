"""Circuito manual con datos PRUEBA: no es una consulta a Computrabajo."""

import pytest

from salta_emplea import db, domain, tasks


ORIGINAL = 'https://ar.computrabajo.com/ofertas-de-trabajo/oferta-de-trabajo-de-prueba-editorial'


@pytest.fixture
def conn(tmp_path):
    target = tmp_path / 'PRUEBA-computrabajo.sqlite'
    db.init_db(target)
    connection = db.connect(target)
    yield connection
    connection.close()


def offer(**changes):
    return {
        'title': 'PRUEBA — Administrativo', 'company': 'EMPRESA FICTICIA',
        'location': 'Orán', 'modality': 'presencial',
        'description': 'Resumen ficticio para probar la revisión; no postularse.',
        'source_name': 'Computrabajo', 'source_url': ORIGINAL,
        **changes,
    }


def test_dos_aportes_normalizados_comparten_oferta_pendiente_y_procedencia(conn):
    first, _ = domain.create_job(conn, offer(source_url=ORIGINAL + '?utm_source=prueba'), 'administrador')
    second, _ = domain.create_job(conn, offer(source_url=ORIGINAL + '#detalle'), 'administrador')
    assert first == second
    assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM provenance').fetchone()[0] == 1
    row = dict(conn.execute('SELECT * FROM jobs').fetchone())
    assert row['status'] == 'pending' and row['approved_at'] is None
    assert row['source_url'] == row['application_url'] == row['source_canonical_url'] == ORIGINAL
    assert row['original_date'] is None and row['salary_amount'] is None
    assert row['last_checked_at'] is None
    assert domain.public_jobs(conn) == []


def test_fuente_repetida_preserva_correccion_y_cambio_material_revoca_aprobacion(conn):
    job_id, _ = domain.create_job(conn, offer(), 'administrador')
    domain.edit_job(conn, job_id, {'description': 'Resumen corregido por el titular.'}, 'administrador')
    domain.transition_job(conn, job_id, 'approve', 'administrador')
    domain.create_job(conn, offer(), 'recopilador_autorizado')
    assert conn.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'approved'
    domain.create_job(conn, offer(company='OTRA EMPRESA FICTICIA'), 'recopilador_autorizado')
    row = conn.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
    assert row['status'] == 'pending' and row['approved_at'] is None
    assert row['description'] == 'Resumen corregido por el titular.'
    assert row['company'] == 'EMPRESA FICTICIA'
    assert row['review_needed'] == 1
    assert domain.public_jobs(conn) == []


def test_parametros_desconocidos_no_pierden_identidad_en_la_clave_unica(conn):
    first, _ = domain.create_job(conn, offer(source_url=ORIGINAL + '?id=2&id=1&utm_source=PRUEBA'), 'administrador')
    second, _ = domain.create_job(conn, offer(source_url=ORIGINAL + '?id=1&id=2'), 'administrador')
    repeated, _ = domain.create_job(conn, offer(source_url=ORIGINAL + '?id=2&id=1&utm_campaign=PRUEBA'), 'administrador')
    assert first != second and repeated == first
    assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 2
    assert conn.execute('SELECT source_canonical_url FROM jobs WHERE id=?', (first,)).fetchone()[0] == ORIGINAL + '?id=2&id=1'


def test_un_aporte_publico_falso_no_retira_una_oferta_aprobada(conn):
    job_id, _ = domain.create_job(conn, offer(), 'administrador')
    domain.transition_job(conn, job_id, 'approve', 'administrador')
    domain.create_job(conn, offer(company='EMPRESA FALSA DE PRUEBA'), 'comunidad')
    row = conn.execute('SELECT status,company FROM jobs WHERE id=?', (job_id,)).fetchone()
    assert tuple(row) == ('approved', 'EMPRESA FICTICIA')


def test_repetir_un_aporte_no_reabre_un_archivado(conn):
    job_id, _ = domain.create_job(conn, offer(), 'administrador')
    domain.transition_job(conn, job_id, 'archive', 'administrador')
    assert domain.create_job(conn, offer(company='EMPRESA NUEVA DE PRUEBA'), 'recopilador_autorizado')[0] == job_id
    assert conn.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'archived'


@pytest.mark.parametrize('changes', [
    {'application_url': 'https://example.test/postularse'},
    {'application_url': 'mailto:cv@example.test'},
    {'description': 'a' * 601}, {'original_text': 'a' * 2001},
    {'source_url': 'https://127.0.0.1/ofertas-de-trabajo/oferta-de-trabajo-prueba'},
    {'source_url': 'https://ar.computrabajo.com.ejemplo.test/ofertas-de-trabajo/oferta-de-trabajo-prueba'},
    {'image_path': 'PRUEBA.jpg'},
])
def test_aportes_invalidos_fallan_antes_de_crear_filas(conn, changes):
    with pytest.raises(ValueError):
        domain.create_job(conn, offer(**changes), 'administrador')
    assert conn.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
    assert conn.execute('SELECT count(*) FROM provenance').fetchone()[0] == 0


def test_aprobar_una_fila_legacy_tambien_valida_el_original(conn):
    job_id, _ = domain.create_job(conn, offer(), 'administrador')
    with conn:
        conn.execute('UPDATE jobs SET application_url=? WHERE id=?', ('https://example.test/otro', job_id))
    with pytest.raises(ValueError):
        domain.transition_job(conn, job_id, 'approve', 'administrador', acknowledge=True)
    assert conn.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'pending'


def test_referencia_incluso_con_booleanos_activos_no_consulta_ni_archiva(conn, monkeypatch):
    monkeypatch.setattr(tasks, 'fetch_json', lambda *_: pytest.fail('No hay acceso de red a Computrabajo.'))
    with conn:
        source_id = conn.execute("INSERT INTO sources(name,url,method,status,authorized) VALUES (?,?, 'manual','active',1)",
            ('Computrabajo', 'https://ar.computrabajo.com/trabajo-en-salta')).lastrowid
    job_id, _ = domain.create_job(conn, offer(), 'administrador')
    domain.transition_job(conn, job_id, 'approve', 'administrador')
    result = tasks.run_tasks(conn, {'SECRET_KEY': 'PRUEBA', 'APP_ENV': 'development'}, only='collect')
    assert result['sources'] == []
    assert conn.execute('SELECT last_run_at FROM sources WHERE id=?', (source_id,)).fetchone()[0] is None
    assert conn.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'approved'


def test_cierre_explicito_y_revision_editorial_reutilizan_el_circuito(conn):
    job_id, _ = domain.create_job(conn, offer(expires_at='2000-01-01'), 'administrador')
    result = domain.expire_jobs(conn, 30)
    assert result['expired'] == 1
    assert conn.execute('SELECT status FROM jobs WHERE id=?', (job_id,)).fetchone()[0] == 'expired'
