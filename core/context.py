def platform_context(request):
    from django.conf import settings
    return {'platform_version': '0.2.0', 'local_development': settings.DEBUG, 'compiler_enabled': settings.COMPILER_ENABLED}
