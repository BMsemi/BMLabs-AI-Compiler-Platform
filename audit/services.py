from .models import AuditEvent

def record(actor, action, obj=None, **details):
    return AuditEvent.objects.create(actor=actor if actor and actor.is_authenticated else None,
        action=action, object_id=str(getattr(obj, 'pk', obj) or ''), details=details)
