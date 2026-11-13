import hashlib
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from audit.services import record
from .models import ProjectFile
from .access import require_edit

ALLOWED_EXTENSIONS = {'.py', '.json', '.yaml', '.yml', '.toml', '.txt', '.csv', '.onnx', '.npy', '.npz', '.v', '.sv', '.pcf'}

def validate_upload(upload):
    name = Path(upload.name.replace('\\', '/')).name
    if not name or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise ValidationError('Invalid filename.')
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValidationError('Unsupported file type. Use source, model, data or constraint files; archives and pickle files are not accepted.')
    if upload.size > settings.MAX_UPLOAD_BYTES or upload.size == 0:
        raise ValidationError('Files must contain data and be no larger than 10 MB.')
    digest = hashlib.sha256()
    count = 0
    for chunk in upload.chunks():
        count += len(chunk)
        if count > settings.MAX_UPLOAD_BYTES:
            raise ValidationError('File exceeds 10 MB.')
        digest.update(chunk)
    upload.seek(0)
    return name, count, digest.hexdigest()

def store_input(user, project, upload):
    require_edit(user, project)
    name, size, digest = validate_upload(upload)
    item = ProjectFile(project=project, uploaded_by=user, name=name, size=size, sha256=digest, file=upload)
    try:
        with transaction.atomic():
            item.save()
            record(user, 'project.file.upload', item, project=str(project.pk), sha256=digest)
    except Exception:
        if item.file and item.file._committed:
            item.file.delete(save=False)
        raise
    return item
