import hashlib
from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail
from django.urls import reverse
from django.http import HttpResponse

def rate_limit(request, scope='auth', limit=15, seconds=900):
    # REMOTE_ADDR is trustworthy; forwarded headers are not accepted here.
    raw = f'{scope}:{request.META.get("REMOTE_ADDR", "unknown")}'
    key = 'rate:' + hashlib.sha256(raw.encode()).hexdigest()
    if cache.add(key, 1, seconds):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, seconds)
            count = 1
    if count > limit:
        response = HttpResponse('Too many attempts. Please try again later.', status=429)
        response['Retry-After'] = str(seconds)
        return response
    return None

def verification_token(user):
    return signing.dumps({'id': user.pk, 'email': user.email}, salt='account-verification')

def send_verification(user):
    link = settings.SITE_URL + reverse('verify-email', args=[verification_token(user)])
    send_mail('Verify your BM Labs account', f'Confirm your email address to activate your account. This link expires in 24 hours.\n\n{link}', settings.DEFAULT_FROM_EMAIL, [user.email])
