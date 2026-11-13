import json
from django.core.management.base import BaseCommand
from compiler.inventory import refresh, inventory_path


class Command(BaseCommand):
    help = 'Probe actual compiler tools and save their version/exit-code evidence.'

    def handle(self, *args, **options):
        data = refresh()
        self.stdout.write(json.dumps({'linear_ready': data['linear_ready'], 'path': str(inventory_path()),
            'tools': {k: v['successful'] for k, v in data['tools'].items()}}))
