"""Resumen operativo local de solo lectura, sin secretos ni alertas externas.

Un cron autenticado prueba una llamada recibida, no quién la inició. El módulo
no infiere programación instalada, entrega de correo ni respaldos de producción.
"""

from datetime import datetime, timezone

from . import db


_TASKS = {"collect": "Recopilación", "expire": "Vigencia", "mail": "Correo"}
_RUN_STATUSES = frozenset({"running", "succeeded", "partial", "failed", "interrupted"})
_MAIL_STATUSES = ("pending", "uncertain", "sent", "failed", "cancelled")
_STATE_LABELS = {
    "sin_evidencia": "Sin evidencia de corridas",
    "en_curso": "Hay una corrida y un bloqueo vigentes",
    "fallo": "La última corrida requiere revisión",
    "antigua": "Última corrida exitosa antigua",
    "reciente": "Lote reciente completado",
    "requiere_revision": "Registro incompleto o fecha inválida",
}


def _threshold(config, name):
    value = config.get(name, 48)
    if isinstance(value, bool):
        return 48
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 48
    return max(1, min(number, 720))


def _timestamp(value, now):
    """Devuelve fechas normalizadas; nunca muestra texto externo sin validar."""
    if not isinstance(value, str) or len(value) > 48:
        return None
    try:
        instant = datetime.fromisoformat(value)
        if instant.tzinfo is None:
            return None
        instant = instant.astimezone(timezone.utc)
        # Un pequeño desfase de reloj no convierte un lote reciente en antiguo.
        if (instant - now).total_seconds() > 300:
            return None
        return instant.isoformat()
    except (ValueError, OverflowError):
        return None


def _age(value, now):
    normalized = _timestamp(value, now)
    if normalized is None:
        return None
    return max(0, (now - datetime.fromisoformat(normalized)).total_seconds() / 3600)


def _run(row, now):
    if row is None:
        return None
    status = row["status"] if row["status"] in _RUN_STATUSES else "unknown"
    started = _timestamp(row["started_at"], now)
    finished = _timestamp(row["finished_at"], now)
    if started and finished and finished < started:
        finished = None
    return {
        "status": status,
        "started_at": started,
        "finished_at": finished,
        "scope": "all" if row["task"] == "all" else "task",
    }


def operations_snapshot(conn, config, *, now=None):
    """SELECT acotados; se puede mostrar únicamente en el panel privado.

    Umbrales de antigüedad configurables, en horas: OPERATIONS_COLLECT_MAX_AGE_HOURS,
    OPERATIONS_EXPIRE_MAX_AGE_HOURS, OPERATIONS_MAIL_MAX_AGE_HOURS y
    OPERATIONS_MAIL_QUEUE_MAX_AGE_HOURS. Por defecto48; límites1..720. No programan
    tareas. No se devuelve actor, detalle libre, dirección, token ni DSN.
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise ValueError("El diagnóstico requiere una fecha con zona horaria.")
    now = now.astimezone(timezone.utc)
    lease_supported = db.is_postgres(conn)
    lease = conn.execute(
        "SELECT expires_at FROM task_locks WHERE name=? LIMIT 1", ("salta-emplea-tasks",),
    ).fetchone() if lease_supported else None
    try:
        lease_epoch = int(lease["expires_at"]) if lease else 0
        lease_active = lease_epoch > now.timestamp()
        lease_until = datetime.fromtimestamp(lease_epoch, timezone.utc).isoformat() if lease_active else None
    except (ValueError, TypeError, OverflowError, OSError):
        lease_active, lease_until = False, None
    entries = []
    for task, label in _TASKS.items():
        threshold = _threshold(config, "OPERATIONS_" + task.upper() + "_MAX_AGE_HOURS")
        cron = conn.execute(
            "SELECT created_at FROM audit WHERE actor='programador' AND action='cron_recibido' AND detail=? ORDER BY id DESC LIMIT 1",
            (task,),
        ).fetchone()
        last = conn.execute(
            "SELECT task,status,started_at,finished_at FROM task_runs WHERE task IN (?, 'all') ORDER BY id DESC LIMIT 1",
            (task,),
        ).fetchone()
        succeeded = conn.execute(
            "SELECT task,status,started_at,finished_at FROM task_runs WHERE task IN (?, 'all') AND status='succeeded' ORDER BY id DESC LIMIT 1",
            (task,),
        ).fetchone()
        received_at = _timestamp(cron["created_at"], now) if cron else None
        cron_age = _age(received_at, now)
        last_run, last_success = _run(last, now), _run(succeeded, now)
        success_at = last_success["finished_at"] if last_success else None
        success_age = _age(success_at, now)
        if last_run is None:
            state = "sin_evidencia"
        elif last_run["status"] in {"failed", "partial", "interrupted"}:
            state = "fallo"
        elif last_run["status"] == "running":
            state = "en_curso" if lease_active and last_run["started_at"] else "requiere_revision"
        elif last_run["status"] == "unknown" or not last_run["started_at"] or success_age is None:
            state = "requiere_revision"
        else:
            state = "antigua" if success_age > threshold else "reciente"
        cron_state = "sin_evidencia"
        if cron:
            cron_state = "requiere_revision" if cron_age is None else "antigua" if cron_age > threshold else "llamadas_recibidas"
        entries.append({
            "task": task, "label": label, "state": state, "state_label": _STATE_LABELS[state],
            "max_age_hours": threshold, "last_run": last_run,
            "last_success_at": success_at, "last_success_age_hours": success_age,
            "cron_state": cron_state, "cron_received_at": received_at,
            "cron_age_hours": cron_age,
        })
    queue = {status: 0 for status in _MAIL_STATUSES}
    oldest_pending = None
    for row in conn.execute(
        "SELECT status,count(*) AS total,MIN(created_at) AS oldest_at FROM outbox WHERE status IN ('pending','uncertain','sent','failed','cancelled') GROUP BY status",
    ).fetchall():
        queue[row["status"]] = int(row["total"])
        if row["status"] == "pending":
            oldest_pending = _timestamp(row["oldest_at"], now)
    queue_threshold = _threshold(config, "OPERATIONS_MAIL_QUEUE_MAX_AGE_HOURS")
    queue_age = _age(oldest_pending, now)
    return {
        "checked_at": now.isoformat(), "tasks": entries,
        "lease": {"supported": lease_supported, "active": lease_active if lease_supported else None, "expires_at": lease_until},
        "scheduler": {
            "state": "no_verificado",
            "message": "Las llamadas autenticadas y corridas manuales no prueban una programación externa activa. Contrastar con el historial del programador.",
        },
        "mail_queue": {
            "counts": queue, "oldest_pending_at": oldest_pending,
            "oldest_pending_age_hours": queue_age,
            "max_age_hours": queue_threshold,
            "needs_review": bool(queue["uncertain"] or queue["failed"] or (queue["pending"] and (queue_age is None or queue_age > queue_threshold))),
            "message": "La cola y la aceptación del proveedor no prueban recepción. Los envíos inciertos requieren conciliación y nunca se reenvían por defecto.",
        },
        "backups": {
            "state": "sin_evidencia_produccion",
            "message": "No hay un registro de copias de producción en esta aplicación. Un ensayo de restauración de CI no prueba un respaldo de producción ni una retención instalada.",
        },
        "external_alerts": {
            "state": "no_configuradas",
            "message": "Este panel muestra registros al consultarlo; no envía alertas ni constituye monitoreo continuo.",
        },
    }
