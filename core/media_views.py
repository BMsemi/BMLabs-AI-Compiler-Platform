"""Authenticated media playback for project artifacts, including byte-range seeking."""
import re
from pathlib import Path

from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_safe

from builds.models import Artifact
from projects.access import visible_projects

MEDIA_TYPES = {'.mp4': 'video/mp4', '.mp3': 'audio/mpeg', '.vtt': 'text/vtt; charset=utf-8'}


def _artifact(request, pk):
    return get_object_or_404(Artifact.objects.filter(
        build__project__in=visible_projects(request.user)), pk=pk)


@login_required
@require_safe
def watch(request, pk):
    artifact = _artifact(request, pk)
    if Path(artifact.name).suffix.lower() != '.mp4':
        raise Http404
    captions = artifact.build.artifacts.filter(
        name=Path(artifact.name).stem + '.vtt').first()
    chapters = artifact.metadata.get('chapters', [])
    return render(request, 'builds/watch.html', {
        'active': 'builds', 'artifact': artifact, 'captions': captions,
        'chapters': chapters if isinstance(chapters, list) else [],
    })


@login_required
@require_safe
def stream(request, pk):
    artifact = _artifact(request, pk)
    content_type = MEDIA_TYPES.get(Path(artifact.name).suffix.lower())
    if content_type is None:
        raise Http404
    try:
        size = artifact.file.size
    except (FileNotFoundError, OSError):
        raise Http404('Media file is unavailable')
    start, end, partial = 0, size - 1, False
    # If-Range validators are not emitted by this no-store endpoint. Serve the
    # complete representation when a client supplies an unrecognised validator.
    range_header = request.headers.get('Range') if request.method == 'GET' and not request.headers.get('If-Range') else None
    if range_header:
        match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header)
        # Ignore malformed or multipart ranges, as allowed by HTTP, without
        # allocating memory for an unbounded client-specified range list.
        if match and any(match.groups()):
            first, last = match.groups()
            try:
                if first:
                    start = int(first)
                    end = min(int(last), size - 1) if last else size - 1
                else:
                    start = max(0, size - int(last))
                partial = True
            except ValueError:
                start, end = 0, size - 1
            if start > end or start >= size:
                response = HttpResponse(status=416)
                response['Content-Range'] = f'bytes */{size}'
                response['Accept-Ranges'] = 'bytes'
                return response
    length = max(0, end - start + 1)
    if request.method == 'HEAD':
        response = HttpResponse(content_type=content_type)
    else:
        try:
            handle = artifact.file.open('rb')
            handle.seek(start)
        except (FileNotFoundError, OSError):
            raise Http404('Media file is unavailable')

        def chunks():
            remaining = length
            try:
                while remaining:
                    data = handle.read(min(64 * 1024, remaining))
                    if not data:
                        break
                    remaining -= len(data)
                    yield data
            finally:
                handle.close()

        response = StreamingHttpResponse(chunks(), status=206 if partial else 200, content_type=content_type)
        # Also close if a disconnected client never starts consuming the iterator.
        response._resource_closers.append(handle.close)
    response['Content-Length'] = str(length)
    response['Content-Disposition'] = 'inline'
    response['Accept-Ranges'] = 'bytes'
    response['Cache-Control'] = 'private, no-store'
    if partial:
        response['Content-Range'] = f'bytes {start}-{end}/{size}'
    return response
