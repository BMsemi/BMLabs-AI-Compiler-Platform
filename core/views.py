from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse, FileResponse
from django.shortcuts import render, get_object_or_404
from accounts.models import User
from organizations.models import Organization
from projects.access import visible_projects
from projects.models import ProjectFile
from builds.models import BuildJob, Artifact, VerificationRun
from audit.models import AuditEvent, APIActivity
from compiler.models import TargetProfile
from compiler.services import capabilities
from django.views.decorators.http import require_POST

@login_required
def dashboard(request):
    projects = visible_projects(request.user)
    builds = BuildJob.objects.filter(project__in=projects)
    return render(request, 'dashboard.html', {'active': 'overview', 'projects': projects[:4], 'recent_builds': builds[:5],
        'project_count': projects.filter(archived=False).count(), 'build_count': builds.count(),
        'file_count': ProjectFile.objects.filter(project__in=projects).count(), 'stages': capabilities(),
        'verified_count': VerificationRun.objects.filter(build__project__in=projects, status='passed').count()})

@login_required
def workspace(request, section='workspace'):
    from compiler.inventory import current
    stages = capabilities()
    selected = next((stage for stage in stages if stage['id'] == section), None)
    details = {
        'python': ('Python to Verilog', 'Start with your model. Keep every input version in a private project workspace.', 'Python source, model files, configuration', 'Versioned source files and input hashes', 'code'),
        'rtl': ('RTL generation', 'Turn a validated graph into hardware-specific RTL, with evidence at every revision.', 'Typed graph IR, target profile, X2 ABI', 'Verilog source, assertions, revision history', 'layers'),
        'fabulous': ('FPGA / eFPGA', 'Map your design to a versioned FABulous fabric and follow implementation evidence.', 'Verified RTL, fabric definition, constraints', 'Netlist, timing reports, FASM, bitstream', 'chip'),
        'x2': ('X2 CIM integration', 'Bring configured fabric and compute-in-memory behavior into the same verification flow.', 'Configured fabric, X2 ABI, numerical oracle', 'Transactions, numerical results, co-simulation report', 'spark'),
        'verification': ('Verification & testing', 'Build confidence with deterministic checks and an independent numerical reference.', 'RTL revisions, assertions, golden model', 'Simulation logs, equivalence results, verification reports', 'check'),
    }
    fallback = (selected['name'], selected['description'], 'Versioned inputs and hardware contracts', 'Structured artifacts and verification evidence', 'terminal') if selected else ('Compiler pipeline', 'A transparent path from Python models to verified hardware.', 'Project source files and model configuration', 'Versioned artifacts and implementation evidence', 'terminal')
    title, description, inputs, outputs, glyph = details.get(section, fallback)
    return render(request, 'workspace.html', {'inventory': current(), 'active': section, 'stages': stages, 'selected_stage': selected,
        'targets': TargetProfile.objects.all(), 'section': section, 'workspace_title': title,
        'workspace_description': description, 'input_description': inputs, 'output_description': outputs,
        'workspace_icon': glyph, 'projects': visible_projects(request.user).filter(archived=False)[:30]})

@login_required
def builds(request):
    jobs = BuildJob.objects.filter(project__in=visible_projects(request.user)).select_related('project')
    if request.GET.get('status') in BuildJob.Status.values:
        jobs = jobs.filter(status=request.GET['status'])
    from django.core.paginator import Paginator
    return render(request, 'builds/index.html', {'active': 'builds', 'jobs': Paginator(jobs, 30).get_page(request.GET.get('page'))})

@login_required
def build_detail(request, pk):
    job = get_object_or_404(BuildJob.objects.filter(project__in=visible_projects(request.user)), pk=pk)
    from projects.access import can_edit
    return render(request, 'builds/detail.html', {'active': 'builds', 'job': job,
        'can_cancel': can_edit(request.user, job.project) and job.status in ('queued', 'running')})

@login_required
@require_POST
def build_cancel(request, pk):
    from builds.services import cancel_build
    from django.shortcuts import redirect
    from django.contrib import messages
    from django.core.exceptions import ValidationError
    job = get_object_or_404(BuildJob.objects.filter(project__in=visible_projects(request.user)), pk=pk)
    try:
        job = cancel_build(request.user, job)
        messages.info(request, job.reason)
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('build-detail', pk=job.pk)

@login_required
def artifact_download(request, pk):
    artifact = get_object_or_404(Artifact.objects.filter(build__project__in=visible_projects(request.user)), pk=pk)
    return FileResponse(artifact.file.open('rb'), as_attachment=True, filename=artifact.name, content_type='application/octet-stream')

def health(request):
    # Liveness only; detailed dependency information is restricted to administrators.
    return JsonResponse({'status': 'ok', 'service': 'bmlabs-platform'})

@user_passes_test(lambda user: user.is_active and user.is_superuser)
def operations(request):
    health = {}
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        health['Database'] = 'Connected'
    except Exception:
        health['Database'] = 'Unavailable'
    try:
        cache.set('platform-health', 'ok', 10)
        health['Cache'] = 'Connected' if cache.get('platform-health') == 'ok' else 'Unavailable'
    except Exception:
        health['Cache'] = 'Unavailable'
    import json
    from pathlib import Path
    from django.conf import settings
    try:
        heartbeat = json.loads((Path(settings.MEDIA_ROOT)/'compiler-worker.json').read_text())
        health['Compiler worker last heartbeat'] = heartbeat['checked_at']
    except (OSError, ValueError, KeyError):
        health['Compiler worker last heartbeat'] = 'No heartbeat recorded'
    health['Compiler adapters'] = 'Linear int8 enabled' if settings.COMPILER_ENABLED else 'Execution disabled'
    return render(request, 'operations.html', {'active': 'operations', 'health': health, 'user_count': User.objects.count(),
        'org_count': Organization.objects.count(), 'events': AuditEvent.objects.select_related('actor')[:20], 'activity': APIActivity.objects.select_related('user')[:20],
        'failed_count': BuildJob.objects.filter(status='failed').count(), 'blocked_count': BuildJob.objects.filter(status='blocked').count()})

@login_required
def api_docs(request):
    return render(request, 'api_docs.html', {'active': 'docs'})
