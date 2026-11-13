from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from audit.services import record
from projects.access import organization_role
from .models import Organization, Membership

@transaction.atomic
def create_organization(user, name, description=''):
    organization = Organization.objects.create(name=name, description=description, created_by=user)
    Membership.objects.create(organization=organization, user=user, role='admin')
    record(user, 'organization.create', organization)
    return organization

@transaction.atomic
def change_member(actor, organization, user, role=None, remove=False):
    # Serialize membership changes, including last-administrator checks.
    organization = Organization.objects.select_for_update().get(pk=organization.pk)
    if organization_role(actor, organization) != 'admin':
        raise PermissionDenied('Organization administrator access is required.')
    membership = Membership.objects.filter(organization=organization, user=user).first()
    if membership and membership.role == 'admin' and (remove or role != 'admin'):
        if organization.memberships.filter(role='admin').count() <= 1:
            raise ValidationError('Keep at least one organization administrator.')
    if remove:
        if membership:
            membership.delete()
    else:
        if role not in Membership.Role.values:
            raise ValidationError('Invalid membership role.')
        if not user.is_active or not user.email_verified:
            raise ValidationError('The member must have an active, verified account.')
        Membership.objects.update_or_create(organization=organization, user=user, defaults={'role': role})
    record(actor, 'organization.member.remove' if remove else 'organization.member.update', organization, user_id=user.pk, role=role)
