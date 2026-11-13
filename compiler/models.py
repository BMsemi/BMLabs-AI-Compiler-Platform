import uuid
from django.db import models

class TargetProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    version = models.CharField(max_length=40)
    fabric_revision = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=24, choices=[('reference', 'Reference only'), ('validated', 'Validated')], default='reference')
    source_url = models.URLField(blank=True)
    source_commit = models.CharField(max_length=64, blank=True)
    resources = models.JSONField(default=dict)
    constraints = models.JSONField(default=dict)
    bitstream_format = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['name', 'version'], name='unique_target_version')]

    def __str__(self):
        return f'{self.name} · {self.version}'

class X2Configuration(models.Model):
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='x2_configurations')
    version = models.PositiveIntegerField(default=1)
    abi_version = models.CharField(max_length=64)
    status = models.CharField(max_length=20, default='draft', choices=[('draft', 'Draft'), ('validated', 'Validated')])
    contract = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['project', 'version'], name='unique_x2_version')]
