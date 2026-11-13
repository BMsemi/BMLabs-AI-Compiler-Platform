from django.urls import path, include
from django.contrib.auth import views as auth
from rest_framework.routers import DefaultRouter
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerSplitView
from rest_framework.permissions import IsAuthenticated
from core import views, api, media_views
from core.admin import site
from accounts import views as accounts
from projects import views as projects
from organizations import views as organizations

router = DefaultRouter()
for prefix, view, basename in [
    ('users', api.UserViewSet, 'users'), ('organizations', api.OrganizationViewSet, 'organizations'),
    ('projects', api.ProjectViewSet, 'projects'), ('files', api.FileViewSet, 'files'),
    ('builds', api.BuildViewSet, 'builds'), ('artifacts', api.ArtifactViewSet, 'artifacts'),
    ('fabulous/targets', api.TargetViewSet, 'targets'), ('ir', api.IRViewSet, 'ir'),
    ('rtl', api.RTLViewSet, 'rtl'), ('verification', api.VerificationViewSet, 'verification'),
    ('x2/configurations', api.X2ViewSet, 'x2-configurations'),
]:
    router.register(prefix, view, basename=basename)

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('health/', views.health, name='health'),
    path('admin/', site.urls), path('operations/', views.operations, name='operations'),
    path('accounts/register/', accounts.register, name='register'),
    path('accounts/login/', accounts.LoginView.as_view(), name='login'),
    path('accounts/logout/', auth.LogoutView.as_view(), name='logout'),
    path('accounts/verify/<str:token>/', accounts.verify_email, name='verify-email'),
    path('accounts/resend/', accounts.resend, name='resend-verification'),
    path('accounts/profile/', accounts.profile, name='profile'), path('accounts/avatar/', accounts.avatar, name='avatar'),
    path('accounts/password-reset/', accounts.PasswordResetView.as_view(), name='password_reset'),
    path('accounts/password-reset/done/', auth.PasswordResetDoneView.as_view(template_name='accounts/reset_done.html'), name='password_reset_done'),
    path('accounts/reset/<uidb64>/<token>/', auth.PasswordResetConfirmView.as_view(template_name='accounts/reset_confirm.html'), name='password_reset_confirm'),
    path('accounts/reset/complete/', auth.PasswordResetCompleteView.as_view(template_name='accounts/reset_complete.html'), name='password_reset_complete'),
    path('projects/', projects.index, name='projects'), path('projects/new/', projects.create, name='project-create'),
    path('projects/<uuid:pk>/', projects.detail, name='project-detail'),
    path('projects/<uuid:pk>/edit/', projects.edit, name='project-edit'),
    path('projects/<uuid:pk>/archive/', projects.archive, name='project-archive'),
    path('projects/<uuid:pk>/upload/', projects.upload, name='project-upload'),
    path('projects/<uuid:pk>/build/', projects.build, name='project-build'),
    path('files/<uuid:pk>/download/', projects.download, name='file-download'),
    path('organizations/', organizations.index, name='organizations'),
    path('organizations/<uuid:pk>/', organizations.detail, name='organization-detail'),
    path('organizations/<uuid:pk>/members/<int:member_id>/remove/', organizations.remove_member, name='member-remove'),
    path('workspace/', views.workspace, name='workspace'), path('workspace/<slug:section>/', views.workspace, name='workspace-section'),
    path('builds/', views.builds, name='builds'), path('builds/<uuid:pk>/', views.build_detail, name='build-detail'),
    path('builds/<uuid:pk>/cancel/', views.build_cancel, name='build-cancel'),
    path('artifacts/<uuid:pk>/download/', views.artifact_download, name='artifact-download'),
    path('artifacts/<uuid:pk>/watch/', media_views.watch, name='artifact-watch'),
    path('artifacts/<uuid:pk>/stream/', media_views.stream, name='artifact-stream'),
    path('api/docs/', views.api_docs, name='api-docs'),
    path('api/schema/', SpectacularAPIView.as_view(permission_classes=[IsAuthenticated]), name='schema'),
    path('api/swagger/', SpectacularSwaggerSplitView.as_view(url_name='schema', permission_classes=[IsAuthenticated]), name='swagger'),
    path('api/v1/auth/<slug:operation>/', api.AuthAPI.as_view(), name='api-auth'),
    path('api/v1/compiler/', api.CapabilityAPI.as_view(), name='compiler-status'),
    path('api/v1/compiler/<slug:section>/', api.StageCapabilityAPI.as_view(), name='compiler-operation'),
    path('api/v1/', include(router.urls)),
]
