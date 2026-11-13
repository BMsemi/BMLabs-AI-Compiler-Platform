import hashlib
from django.core.files.base import ContentFile
from .models import Artifact


def save_artifact(build, name, data, kind='report', metadata=None):
    artifact = Artifact(build=build, name=name, kind=kind,
        sha256=hashlib.sha256(data).hexdigest(), metadata={**(metadata or {}), 'size_bytes': len(data)})
    artifact.file.save(name, ContentFile(data), save=True)
    return artifact
