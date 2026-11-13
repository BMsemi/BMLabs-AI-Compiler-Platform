import uuid
from django.conf import settings
from django.db import models

class BuildJob(models.Model):
    class Status(models.TextChoices):
        BLOCKED = 'blocked', 'Blocked'
        QUEUED = 'queued', 'Queued'
        RUNNING = 'running', 'Running'
        SUCCEEDED = 'succeeded', 'Succeeded'
        FAILED = 'failed', 'Failed'
        CANCELLED = 'cancelled', 'Cancelled'
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project = models.ForeignKey('projects.Project', on_delete=models.CASCADE, related_name='builds')
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    target = models.ForeignKey('compiler.TargetProfile', on_delete=models.PROTECT, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.BLOCKED)
    compiler_version = models.CharField(max_length=64, default='not-connected')
    ir_schema_version = models.CharField(max_length=32, default='1.0')
    x2_abi_version = models.CharField(max_length=64, blank=True)
    configuration = models.JSONField(default=dict)
    input_manifest = models.JSONField(default=list)
    target_snapshot = models.JSONField(default=dict)
    x2_snapshot = models.JSONField(default=dict)
    reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

class BuildLog(models.Model):
    build = models.ForeignKey(BuildJob, on_delete=models.CASCADE, related_name='logs')
    stage = models.CharField(max_length=40)
    level = models.CharField(max_length=10, default='info')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

class BuildStage(models.Model):
    build = models.ForeignKey(BuildJob, on_delete=models.CASCADE, related_name='stages')
    name = models.CharField(max_length=80)
    status = models.CharField(max_length=16, default='running')
    evidence = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']

def artifact_path(instance, filename):
    return f'builds/{instance.build_id}/artifacts/{uuid.uuid4().hex}'

class Artifact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    build = models.ForeignKey(BuildJob, on_delete=models.CASCADE, related_name='artifacts')
    kind = models.CharField(max_length=24, choices=[('source', 'Source'), ('log', 'Log'), ('ir', 'IR'), ('rtl', 'RTL'), ('bitstream', 'Bitstream'), ('report', 'Report')])
    file = models.FileField(upload_to=artifact_path)
    name = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    metadata = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

class IRVersion(models.Model):
    build = models.ForeignKey(BuildJob, on_delete=models.CASCADE, related_name='ir_versions')
    version = models.PositiveIntegerField(default=1)
    schema_version = models.CharField(max_length=32)
    graph = models.JSONField(default=dict)
    artifact = models.OneToOneField(Artifact, on_delete=models.PROTECT, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['build', 'version'], name='unique_ir_version')]

class RTLRevision(models.Model):
    build = models.ForeignKey(BuildJob, on_delete=models.CASCADE, related_name='rtl_revisions')
    version = models.PositiveIntegerField(default=1)
    ir = models.ForeignKey(IRVersion, on_delete=models.PROTECT)
    artifact = models.OneToOneField(Artifact, on_delete=models.PROTECT)
    provider = models.CharField(max_length=120)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['build', 'version'], name='unique_rtl_version')]

class VerificationRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    build = models.ForeignKey(BuildJob, on_delete=models.CASCADE, related_name='verifications')
    rtl = models.ForeignKey(RTLRevision, on_delete=models.PROTECT, null=True, blank=True)
    stage = models.CharField(max_length=16, choices=[(v, v) for v in ['rtl', 'rtl_netlist', 'equivalence', 'x2_candidate', 'fabric_reference', 'logical_pe', 'physical_fpga', 'V0', 'V1', 'V2', 'V3', 'V4']])
    status = models.CharField(max_length=16, choices=[('pending', 'Pending'), ('passed', 'Passed'), ('failed', 'Failed')], default='pending')
    report = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

class BitstreamArtifact(models.Model):
    build = models.OneToOneField(BuildJob, on_delete=models.CASCADE, related_name='bitstream')
    artifact = models.OneToOneField(Artifact, on_delete=models.PROTECT)
    fabric_revision = models.CharField(max_length=120)
    format_version = models.CharField(max_length=40)
    frame_count = models.PositiveIntegerField()
