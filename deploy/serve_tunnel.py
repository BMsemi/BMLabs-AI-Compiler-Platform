"""Single-process Windows origin, reachable only through loopback."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def configure():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
    os.environ.update({
        'DJANGO_SETTINGS_MODULE': 'config.settings',
        'DJANGO_DEBUG': '0',
        'BMLABS_SINGLE_HOST': '1',
        'DJANGO_ALLOWED_HOSTS': 'ai.bmsemiconnect.com',
        'SITE_URL': 'https://ai.bmsemiconnect.com',
        'CSRF_TRUSTED_ORIGINS': 'https://ai.bmsemiconnect.com',
        'TRUST_PROXY': '1',
    })
    # Reuse the existing application's key and database, without printing secrets.
    if not os.environ.get('DJANGO_SECRET_KEY'):
        os.environ['DJANGO_SECRET_KEY'] = (ROOT / '.local-secret').read_text().strip()


if __name__ == '__main__':
    configure()
    if len(sys.argv) > 1:
        from django.core.management import execute_from_command_line
        execute_from_command_line([sys.argv[0], *sys.argv[1:]])
    else:
        from config.wsgi import application
        from waitress import serve
        serve(application, host='127.0.0.1', port=18765, threads=4,
              trusted_proxy='127.0.0.1', trusted_proxy_count=1,
              trusted_proxy_headers={'x-forwarded-proto', 'x-forwarded-for'},
              clear_untrusted_proxy_headers=True,
              max_request_body_size=12 * 1024 * 1024)
