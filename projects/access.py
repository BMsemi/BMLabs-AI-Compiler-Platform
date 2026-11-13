from django.db.models import Q
from django.core.exceptions import PermissionDenied
from organizations.models import Membership
from .models import Project

def visible_projects(user):
    if not user.is_authenticated:
        return Project.objects.none()
    if user.is_superuser:
        return Project.objects.all()
    return Project.objects.filter(Q(organization__isnull=True, owner=user) | Q(organization__memberships__user=user)).distinct()

def organization_role(user, organization):
    if user.is_superuser:
        return 'admin'
    return Membership.objects.filter(organization=organization, user=user).values_list('role', flat=True).first()

def can_edit(user, project):
    if user.is_superuser:
        return True
    if project.organization_id:
        return organization_role(user, project.organization) in ['admin', 'editor']
    return project.owner_id == user.pk

def can_manage(user, project):
    if user.is_superuser:
        return True
    if project.organization_id:
        return organization_role(user, project.organization) == 'admin'
    return project.owner_id == user.pk

def require_edit(user, project):
    if not can_edit(user, project) or project.archived:
        raise PermissionDenied('Editor access to an active project is required.')
