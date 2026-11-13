from django.core.management.base import BaseCommand
from compiler.models import TargetProfile

class Command(BaseCommand):
    help = 'Create an upstream reference catalog, never a validated BM Labs hardware target.'

    def handle(self, *args, **options):
        commit = '39b5ee6e2db509aba315bf9866759e81a5b8c722'
        target, created = TargetProfile.objects.get_or_create(name='FABulous upstream primitives', version=commit[:12], defaults={
            'status': 'reference', 'source_commit': commit,
            'source_url': f'https://github.com/mole99/fabulous-tiles/tree/{commit}/primitives',
            'resources': {'catalog_only': True, 'primitives': ['FABULOUS_LC', 'GBUF', 'IBUF', 'IDDR',
                'IHP_SRAM_1024x16_2RW', 'IHP_SRAM_1024x32_1RW', 'IOBUF', 'MACC_8x8_20', 'OBUF', 'ODDR',
                'RAM_32x4_2R_1W', 'SYS_RESET', 'TBUF', 'TT_PROJECT', 'TT_PROJECT_LARGE', 'TT_PROJECT_MUX', 'WARMBOOT'],
                'physical_inventory_verified': False},
            'constraints': {'note': 'BM Labs tile counts, routing, pins, clocks and timing models are not frozen.'},
        })
        self.stdout.write(self.style.SUCCESS(('Created' if created else 'Already present') + ': ' + str(target)))
