from .models import AuditLog


def audit(entity, entity_id, event, actor=None, from_state="", to_state="", detail=None):
    """Single write path to the append-only audit log (spec §7.2).
    Callers must never pass sensitive values (basic_pay, passport_no,
    contract_value) in `detail` — NFR: excluded from logs."""
    AuditLog.objects.create(
        entity=entity,
        entity_id=entity_id,
        event=event,
        actor=actor,
        from_state=from_state or "",
        to_state=to_state or "",
        detail=detail,
    )
