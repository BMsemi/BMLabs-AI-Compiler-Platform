from io import BytesIO
from PIL import Image, UnidentifiedImageError
from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.core.files.base import ContentFile
from .models import User

class RegistrationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ['full_name', 'email', 'password1', 'password2']

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('An account with this email already exists. Try signing in or resetting your password.')
        return email

class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label='Email address')

    def clean_username(self):
        return self.cleaned_data['username'].strip().lower()

class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['full_name', 'company', 'contact', 'avatar']

    def clean_avatar(self):
        upload = self.cleaned_data.get('avatar')
        if not upload or not hasattr(upload, 'content_type'):
            return upload
        if upload.size > 2 * 1024 * 1024:
            raise forms.ValidationError('Profile images must be at most 2 MB.')
        try:
            with Image.open(upload) as img:
                if img.format not in {'JPEG', 'PNG'} or img.width * img.height > 16_000_000:
                    raise ValueError()
                img.thumbnail((512, 512))
                output = BytesIO()
                img.convert('RGB').save(output, format='PNG')
            return ContentFile(output.getvalue(), name='avatar.png')
        except (ValueError, UnidentifiedImageError, OSError, Image.DecompressionBombError):
            raise forms.ValidationError('Use a valid PNG or JPEG smaller than 16 megapixels.')
