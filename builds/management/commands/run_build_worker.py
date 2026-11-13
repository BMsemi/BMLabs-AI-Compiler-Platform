import json
import os
import time
from datetime import timedelta
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from builds.models import BuildJob, BuildLog, BuildStage
from builds.runner import claim_next, execute, recover_interrupted
from pathlib import Path
from compiler.execution import write_json


class Command(BaseCommand):
    help = 'Run the single-host compiler queue. Only fixed, bounded adapters execute.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true')

    def handle(self, *args, **options):
        if not settings.COMPILER_ENABLED:
            raise CommandError('COMPILER_ENABLED must be enabled by the administrator.')
        media = Path(settings.MEDIA_ROOT)
        media.mkdir(parents=True, exist_ok=True)
        lock = (media/'compiler-worker.lock').open('a+b')
        lock.seek(0)
        if not lock.read(1):
            lock.write(b'0'); lock.flush()
        lock.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise CommandError('A compiler worker is already running for this media directory.')
        # Holding the exclusive worker lock means prior running jobs lost their worker.
        recover_interrupted()
        try:
            while True:
                heartbeat = media/'compiler-worker.json'
                write_json(heartbeat, {'pid': os.getpid(), 'checked_at': timezone.now().isoformat()})
                job = claim_next()
                if job:
                    try:
                        execute(job)
                    except Exception as exc:
                        BuildJob.objects.filter(pk=job.pk).update(status='failed', completed_at=timezone.now(), reason=f'Worker error: {exc}')
                    job.refresh_from_db()
                    self.stdout.write(json.dumps({'build': str(job.pk), 'status': job.status, 'reason': job.reason}))
                    self.stdout.flush()
                if options['once']:
                    break
                if not job:
                    time.sleep(2)
        finally:
            lock.close()
