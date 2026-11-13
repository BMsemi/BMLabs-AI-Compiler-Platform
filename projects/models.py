import uuid
from django.conf import settings
from django.db import models

class Project(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True, max_length=4000)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='owned_projects')
    organization = models.ForeignKey('organizations.Organization', on_delete=models.PROTECT, null=True, blank=True, related_name='projects')
    target = models.ForeignKey('compiler.TargetProfile', on_delete=models.PROTECT, null=True, blank=True)
    archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return self.name

def input_path(instance, filename):
    return f'projects/{instance.project_id}/inputs/{uuid.uuid4().hex}'

class ProjectFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='files')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=255)
    file = models.FileField(upload_to=input_path)
    size = models.PositiveBigIntegerField()
    sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

class CompilerConfiguration(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='configurations')
    version = models.PositiveIntegerField(default=1)
    schema_version = models.CharField(max_length=32, default='1.0')
    settings = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'version'], name='unique_configuration_version')]
