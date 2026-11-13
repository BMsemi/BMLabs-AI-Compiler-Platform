from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import render, redirect
from django.views.decorators.http import require_http_methods
from audit.services import record
from .forms import RegistrationForm, ProfileForm, EmailAuthenticationForm
from .models import User
from .services import rate_limit, send_verification

class LoginView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    authentication_form = EmailAuthenticationForm

    def post(self, request, *args, **kwargs):
        limited = rate_limit(request)
        return limited if limited is not None else super().post(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        record(self.request.user, 'account.login')
        return response

class PasswordResetView(auth_views.PasswordResetView):
    template_name = 'accounts/reset.html'
    email_template_name = 'accounts/reset_email.txt'
    subject_template_name = 'accounts/reset_subject.txt'

    def post(self, request, *args, **kwargs):
        limited = rate_limit(request, 'reset', 5)
        return limited if limited is not None else super().post(request, *args, **kwargs)

    def form_valid(self, form):
        from urllib.parse import urlparse
        self.extra_email_context = {'domain': urlparse(settings.SITE_URL).netloc, 'protocol': urlparse(settings.SITE_URL).scheme}
        return super().form_valid(form)

@require_http_methods(['GET', 'POST'])
def register(request):
    if request.method == 'POST':
        limited = rate_limit(request, 'register', 8)
        if limited is not None:
            return limited
    form = RegistrationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                record(user, 'account.register')
        except IntegrityError:
            form.add_error('email', 'This email is already registered.')
        else:
            send_verification(user)
            return render(request, 'accounts/message.html', {'title': 'Check your inbox', 'text': 'Use the verification link to activate your account. For local development, email is printed in the server console.'})
    return render(request, 'accounts/register.html', {'form': form})

@require_http_methods(['GET', 'POST'])
def verify_email(request, token):
    try:
        data = signing.loads(token, salt='account-verification', max_age=86400)
        user = User.objects.get(pk=data['id'], email=data['email'])
    except (signing.BadSignature, User.DoesNotExist, KeyError):
        return render(request, 'accounts/message.html', {'title': 'Link unavailable', 'text': 'This verification link is invalid or expired. Request a new link.'}, status=400)
    if user.suspended or (user.email_verified and not user.is_active):
        return render(request, 'accounts/message.html', {'title': 'Account unavailable', 'text': 'Contact your platform administrator.'}, status=403)
    if request.method == 'POST':
        if not user.email_verified:
            user.email_verified = True
            user.is_active = True
            user.save()
            record(user, 'account.verify')
        messages.success(request, 'Email verified. You can now sign in.')
        return redirect('login')
    return render(request, 'accounts/verify.html')

@require_http_methods(['GET', 'POST'])
def resend(request):
    from django import forms
    class ResendForm(forms.Form):
        email = forms.EmailField()
    form = ResendForm(request.POST or None)
    if request.method == 'POST':
        limited = rate_limit(request, 'resend', 5)
        if limited is not None:
            return limited
        if form.is_valid():
            user = User.objects.filter(email__iexact=form.cleaned_data['email'], email_verified=False, suspended=False).first()
            if user:
                send_verification(user)
            return render(request, 'accounts/message.html', {'title': 'Check your inbox', 'text': 'If an eligible account exists, a new verification link has been sent.'})
    return render(request, 'accounts/resend.html', {'form': form})

@login_required
@require_http_methods(['GET', 'POST'])
def profile(request):
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == 'POST' and form.is_valid():
        form.save()
        record(request.user, 'account.profile.update')
        messages.success(request, 'Profile updated.')
        return redirect('profile')
    return render(request, 'accounts/profile.html', {'form': form, 'active': 'profile'})

@login_required
def avatar(request):
    if not request.user.avatar:
        raise Http404
    return FileResponse(request.user.avatar.open('rb'), content_type='image/png')
