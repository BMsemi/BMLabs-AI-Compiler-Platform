from urllib.parse import urlparse
from django.conf import settings
from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import PasswordResetForm, AdminUserCreationForm
from django.core.exceptions import PermissionDenied
from accounts.models import User
from organizations.models import Organization, Membership
from projects.models import Project, ProjectFile, CompilerConfiguration
from compiler.models import TargetProfile, X2Configuration
from builds.models import BuildJob, BuildLog, Artifact, IRVersion, RTLRevision, VerificationRun, BitstreamArtifact
from audit.models import AuditEvent, APIActivity
from audit.services import record
from accounts.services import rate_limit

class PlatformAdminSite(admin.AdminSite):
    site_header = 'BM Labs · Super administration'
    site_title = 'BM Labs Administration'
    index_title = 'Platform control'

    def has_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def login(self, request, extra_context=None):
        if request.method == 'POST':
            limited = rate_limit(request, 'admin-login', 10)
            if limited is not None:
                return limited
        return super().login(request, extra_context)

site = PlatformAdminSite(name='platform_admin')

class AuditedAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record(request.user, 'admin.update' if change else 'admin.create', obj, model=obj._meta.label)

    def delete_model(self, request, obj):
        record(request.user, 'admin.delete', obj, model=obj._meta.label)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            record(request.user, 'admin.delete', obj, model=obj._meta.label)
        super().delete_queryset(request, queryset)

class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request): return False
    def has_change_permission(self, request, obj=None): return False
    def has_delete_permission(self, request, obj=None): return False

class AccountCreationForm(AdminUserCreationForm):
    class Meta(AdminUserCreationForm.Meta):
        model = User
        fields = ('email', 'full_name')

@admin.action(description='Send secure password reset emails')
def send_reset(modeladmin, request, queryset):
    site_url = urlparse(settings.SITE_URL)
    for user in queryset.filter(is_active=True):
        form = PasswordResetForm({'email': user.email})
        if form.is_valid():
            form.save(use_https=site_url.scheme == 'https', domain_override=site_url.netloc,
                from_email=settings.DEFAULT_FROM_EMAIL, email_template_name='accounts/reset_email.txt', subject_template_name='accounts/reset_subject.txt')
            record(request.user, 'admin.password.reset.request', user)
    modeladmin.message_user(request, 'Reset instructions sent to eligible accounts.', messages.SUCCESS)

class AccountAdmin(UserAdmin, AuditedAdmin):
    add_form = AccountCreationForm
    ordering = ['email']
    list_display = ['email', 'full_name', 'email_verified', 'is_active', 'suspended', 'last_login']
    list_filter = ['email_verified', 'is_active', 'suspended', 'is_superuser']
    search_fields = ['email', 'full_name', 'company']
    readonly_fields = ['date_joined', 'last_login']
    fieldsets = (
        ('Account', {'fields': ('email', 'password', 'full_name', 'company', 'contact')}),
        ('Access', {'fields': ('email_verified', 'is_active', 'suspended', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('History', {'fields': ('date_joined', 'last_login')}),
    )
    add_fieldsets = ((None, {'fields': ('email', 'full_name', 'password1', 'password2')}),)
    actions = [send_reset]

    def user_change_password(self, request, id, form_url=''):
        raise PermissionDenied('Use the secure reset email action.')

class ProjectAdmin(AuditedAdmin):
    list_display = ['name', 'owner', 'organization', 'archived', 'updated_at']
    list_filter = ['archived', 'organization']
    search_fields = ['name', 'owner__email']

class MembershipAdmin(ReadOnlyAdmin):
    list_display = ['organization', 'user', 'role']
    list_filter = ['role', 'organization']

class BuildAdmin(ReadOnlyAdmin):
    list_display = ['id', 'project', 'status', 'created_at']
    list_filter = ['status']

class EventAdmin(ReadOnlyAdmin):
    list_display = ['created_at', 'actor', 'action', 'object_id']
    list_filter = ['action']
    search_fields = ['actor__email', 'object_id']

site.register(User, AccountAdmin)
site.register(Project, ProjectAdmin)
site.register(Organization, AuditedAdmin)
site.register(Membership, MembershipAdmin)
site.register(BuildJob, BuildAdmin)
site.register(AuditEvent, EventAdmin)
for model in [ProjectFile, BuildLog, Artifact, IRVersion, RTLRevision, VerificationRun, BitstreamArtifact, APIActivity]:
    site.register(model, ReadOnlyAdmin)
for model in [TargetProfile, X2Configuration, CompilerConfiguration]:
    site.register(model, AuditedAdmin)
