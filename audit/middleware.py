import logging
from .models import APIActivity

class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path.startswith('/api/'):
            try:
                APIActivity.objects.create(user=request.user if request.user.is_authenticated else None,
                    method=request.method, route=(getattr(request.resolver_match, 'route', '') or 'unmatched')[:255], status_code=response.status_code)
            except Exception:
                logging.getLogger(__name__).exception('Could not persist API activity')
        return response
