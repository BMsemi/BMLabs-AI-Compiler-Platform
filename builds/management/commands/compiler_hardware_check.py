import json
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from builds.models import BuildJob, BuildStage
from builds.artifacts import save_artifact
from compiler.hardware import inspect_x2, fabulous_preflight


class Command(BaseCommand):
    help = 'Attach real hardware diagnostics to a completed Linear milestone; never reports hardware verification.'

    def add_arguments(self, parser):
        parser.add_argument('--build', required=True)

    def handle(self, *args, **options):
        job = BuildJob.objects.get(pk=options['build'])
        if job.status != 'succeeded' or not job.verifications.filter(stage='rtl', status='passed').exists():
            raise CommandError('First complete a real Linear RTL milestone.')
        out = Path(settings.MEDIA_ROOT)/'work'/str(job.pk)/'hardware-inspection'
        report = {'fabulous': fabulous_preflight(job.target), 'x2': inspect_x2(out)}
        save_artifact(job, 'hardware-inspection.json', json.dumps(report, indent=2).encode())
        for result in report['x2']['commands']:
            BuildStage.objects.create(build=job, name=result['stage'],
                status='successful' if result['successful'] else 'failed', evidence=result)
        for path in out.iterdir():
            if path.is_file():
                save_artifact(job, 'candidate_x2/' + path.name, path.read_bytes(), 'rtl' if path.suffix == '.v' else 'report')
        self.stdout.write(json.dumps({'fabulous': report['fabulous'], 'x2_status': report['x2']['status'],
            'exit_codes': [r['exit_code'] for r in report['x2']['commands']]}))
