from django import forms
from organizations.models import Organization
from .models import Project

class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ['name', 'description', 'organization', 'target']
        widgets = {'description': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['organization'].queryset = Organization.objects.all() if user.is_superuser else Organization.objects.filter(memberships__user=user, memberships__role__in=['admin', 'editor'])
        if not self.instance._state.adding:
            self.fields.pop('organization')

class UploadForm(forms.Form):
    file = forms.FileField(label='Source or model file', help_text='Up to 10 MB. Python, ONNX, NumPy, RTL, JSON, YAML, TOML, CSV, TXT or PCF.')
