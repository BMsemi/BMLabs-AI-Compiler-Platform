class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response['Referrer-Policy'] = 'same-origin'
        response['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        # Swagger uses inline styles, but split view keeps all scripts same-origin.
        if request.path == '/api/swagger/':
            response['Content-Security-Policy'] = response['Content-Security-Policy'].replace("style-src 'self'", "style-src 'self' 'unsafe-inline'")
        if request.user.is_authenticated:
            response['Cache-Control'] = 'no-store'
        return response
