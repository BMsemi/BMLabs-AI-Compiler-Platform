from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from django.views.decorators.http import require_http_methods, require_POST
from accounts.models import User
from projects.access import organization_role
from .models import Organization, Membership
from .services import create_organization, change_member

class OrganizationForm(forms.ModelForm):
    class Meta:
        model = Organization
        fields = ['name', 'description']

class MemberForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=Membership.Role.choices)

def visible_organizations(user):
    return Organization.objects.all() if user.is_superuser else Organization.objects.filter(memberships__user=user)

@login_required
@require_http_methods(['GET', 'POST'])
def index(request):
    form = OrganizationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        org = create_organization(request.user, **form.cleaned_data)
        return redirect('organization-detail', pk=org.pk)
    return render(request, 'organizations/index.html', {'organizations': visible_organizations(request.user), 'form': form, 'active': 'organizations'})

@login_required
@require_http_methods(['GET', 'POST'])
def detail(request, pk):
    org = get_object_or_404(visible_organizations(request.user), pk=pk)
    is_admin = organization_role(request.user, org) == 'admin'
    form = MemberForm(request.POST or None)
    if request.method == 'POST':
        if not is_admin:
            raise PermissionDenied
        if form.is_valid():
            user = User.objects.filter(email__iexact=form.cleaned_data['email']).first()
            if not user:
                form.add_error('email', 'No eligible account found. Ask this person to register and verify their email first.')
            else:
                try:
                    change_member(request.user, org, user, form.cleaned_data['role'])
                except ValidationError as exc:
                    form.add_error(None, exc)
                else:
                    messages.success(request, 'Membership saved.')
                    return redirect('organization-detail', pk=pk)
    return render(request, 'organizations/detail.html', {'organization': org, 'members': org.memberships.select_related('user'), 'is_org_admin': is_admin, 'form': form, 'active': 'organizations'})

@login_required
@require_POST
def remove_member(request, pk, member_id):
    org = get_object_or_404(visible_organizations(request.user), pk=pk)
    membership = get_object_or_404(org.memberships, pk=member_id)
    try:
        change_member(request.user, org, membership.user, remove=True)
    except ValidationError as exc:
        messages.error(request, '; '.join(exc.messages))
    return redirect('organizations' if membership.user_id == request.user.pk else 'organization-detail', **({} if membership.user_id == request.user.pk else {'pk': pk}))
