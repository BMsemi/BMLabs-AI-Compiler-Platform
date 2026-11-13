from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_POST, require_http_methods
from audit.services import record
from builds.services import request_build
from .access import visible_projects, require_edit, can_edit, can_manage
from .forms import ProjectForm, UploadForm
from .models import ProjectFile
from .services import store_input

@login_required
def index(request):
    projects = visible_projects(request.user).select_related('organization', 'target')
    query = request.GET.get('q', '').strip()
    if query:
        projects = projects.filter(name__icontains=query)
    if request.GET.get('status') == 'archived':
        projects = projects.filter(archived=True)
    else:
        projects = projects.filter(archived=False)
    return render(request, 'projects/index.html', {'projects': projects, 'query': query, 'active': 'projects'})

@login_required
@require_http_methods(['GET', 'POST'])
def create(request):
    form = ProjectForm(request.POST or None, user=request.user)
    if request.method == 'POST' and form.is_valid():
        project = form.save(commit=False)
        project.owner = request.user
        project.save()
        record(request.user, 'project.create', project)
        messages.success(request, 'Project created. Upload your first source file to get started.')
        return redirect('project-detail', pk=project.pk)
    return render(request, 'projects/form.html', {'form': form, 'title': 'Create a project', 'active': 'projects'})

@login_required
def detail(request, pk):
    project = get_object_or_404(visible_projects(request.user), pk=pk)
    return render(request, 'projects/detail.html', {'project': project, 'upload_form': UploadForm(),
        'editable': can_edit(request.user, project) and not project.archived, 'manageable': can_manage(request.user, project), 'active': 'projects'})

@login_required
@require_http_methods(['GET', 'POST'])
def edit(request, pk):
    project = get_object_or_404(visible_projects(request.user), pk=pk)
    require_edit(request.user, project)
    form = ProjectForm(request.POST or None, instance=project, user=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        record(request.user, 'project.update', project)
        return redirect('project-detail', pk=pk)
    return render(request, 'projects/form.html', {'form': form, 'title': 'Project settings', 'active': 'projects'})

@login_required
@require_http_methods(['GET', 'POST'])
def archive(request, pk):
    project = get_object_or_404(visible_projects(request.user), pk=pk)
    if not can_manage(request.user, project):
        raise PermissionDenied
    if request.method == 'POST':
        project.archived = not project.archived
        project.save(update_fields=['archived', 'updated_at'])
        record(request.user, 'project.archive' if project.archived else 'project.restore', project)
        return redirect('project-detail', pk=pk)
    return render(request, 'projects/confirm.html', {'project': project, 'active': 'projects'})

@login_required
@require_POST
def upload(request, pk):
    project = get_object_or_404(visible_projects(request.user), pk=pk)
    require_edit(request.user, project)
    form = UploadForm(request.POST, request.FILES)
    if form.is_valid():
        try:
            store_input(request.user, project, form.cleaned_data['file'])
            messages.success(request, 'File uploaded. SHA-256 recorded for build traceability.')
        except ValidationError as exc:
            messages.error(request, '; '.join(exc.messages))
    else:
        messages.error(request, 'Choose a valid file to upload.')
    return redirect('project-detail', pk=pk)

@login_required
def download(request, pk):
    item = get_object_or_404(ProjectFile.objects.filter(project__in=visible_projects(request.user)), pk=pk)
    record(request.user, 'project.file.download', item)
    return FileResponse(item.file.open('rb'), as_attachment=True, filename=item.name, content_type='application/octet-stream')

@login_required
@require_POST
def build(request, pk):
    project = get_object_or_404(visible_projects(request.user), pk=pk)
    job = request_build(request.user, project, request.POST.get('pipeline'), request.POST.get('entrypoint', 'model.py'))
    messages.info(request, job.reason)
    return redirect('build-detail', pk=job.pk)
