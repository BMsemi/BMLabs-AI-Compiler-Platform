from urllib.parse import urlparse
from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.core import signing
from django.core.exceptions import ValidationError as DjangoValidationError, PermissionDenied as DjangoPermissionDenied
from django.db import transaction, IntegrityError
from django.http import FileResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils.decorators import method_decorator
from django.utils.http import urlsafe_base64_decode
from django.views.decorators.csrf import csrf_protect
from rest_framework import serializers, viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, inline_serializer, OpenApiTypes, OpenApiParameter
from accounts.models import User
from accounts.forms import RegistrationForm
from accounts.services import send_verification, rate_limit
from organizations.models import Organization, Membership
from organizations.services import create_organization, change_member
from organizations.views import visible_organizations
from projects.models import Project, ProjectFile, CompilerConfiguration
from projects.access import visible_projects, can_edit, can_manage, organization_role
from projects.services import store_input
from builds.models import BuildJob, BuildLog, Artifact, IRVersion, RTLRevision, VerificationRun
from builds.services import request_build, cancel_build
from compiler.models import TargetProfile, X2Configuration
from compiler.services import capabilities
from audit.services import record

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'full_name', 'company', 'contact', 'date_joined', 'last_login', 'email_verified', 'is_active']
        read_only_fields = ['id', 'email', 'date_joined', 'last_login', 'email_verified', 'is_active']

class AuthInput(serializers.Serializer):
    email = serializers.EmailField(required=False)
    password = serializers.CharField(required=False, write_only=True)
    password1 = serializers.CharField(required=False, write_only=True)
    password2 = serializers.CharField(required=False, write_only=True)
    full_name = serializers.CharField(required=False)
    token = serializers.CharField(required=False)
    uid = serializers.CharField(required=False)

class AuthResult(serializers.Serializer):
    detail = serializers.CharField(required=False)
    user = UserSerializer(required=False)
    csrfToken = serializers.CharField(required=False)

class BuildLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuildLog
        fields = ['stage', 'level', 'message', 'created_at']

class BuildRequestSerializer(serializers.Serializer):
    pipeline = serializers.CharField(required=False, help_text='Supported: linear-int8-v1, linear-synth-v1, linear-fpga-v1 (administrator), x2-candidate-v1, fabulous-reference-v1, zcu106-preflight-v1.')
    entrypoint = serializers.CharField(default='model.py', help_text='Exact name of a previously uploaded supported Python input.')

class BuildRequestResult(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    detail = serializers.CharField()

class StageEvidenceSerializer(serializers.Serializer):
    name = serializers.CharField()
    status = serializers.CharField()
    evidence = serializers.JSONField()

@method_decorator(csrf_protect, name='dispatch')
class AuthAPI(APIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = AuthInput

    @extend_schema(parameters=[OpenApiParameter('operation', str, OpenApiParameter.PATH, enum=['session'])], responses=inline_serializer('SessionInfo', fields={'csrfToken': serializers.CharField(), 'user': UserSerializer(allow_null=True)}))
    def get(self, request, operation):
        if operation != 'session':
            return Response({'detail': 'Use POST for this operation.'}, status=405)
        return Response({'csrfToken': get_token(request), 'user': UserSerializer(request.user).data if request.user.is_authenticated else None})

    @extend_schema(request=AuthInput, parameters=[OpenApiParameter('operation', str, OpenApiParameter.PATH, enum=['login', 'logout', 'register', 'verify', 'resend', 'password-reset', 'password-reset-confirm'])], responses={200: AuthResult, 201: AuthResult, 400: None, 403: None, 429: None})
    def post(self, request, operation):
        limited = rate_limit(request, f'api-auth-{operation}', 10)
        if limited is not None:
            return Response({'detail': 'Too many attempts.'}, status=429, headers={'Retry-After': '900'})
        payload = AuthInput(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        if operation == 'login':
            user = authenticate(request, username=str(data.get('email', '')).strip().lower(), password=data.get('password', ''))
            if user is None:
                return Response({'detail': 'Invalid credentials or account not active.'}, status=400)
            login(request, user)
            record(user, 'account.login')
            return Response({'user': UserSerializer(user).data, 'csrfToken': get_token(request)})
        if operation == 'logout':
            record(request.user, 'account.logout')
            logout(request)
            return Response({'detail': 'Signed out.'})
        if operation == 'register':
            form = RegistrationForm(data)
            if not form.is_valid():
                return Response(form.errors, status=400)
            try:
                with transaction.atomic():
                    user = form.save()
                    record(user, 'account.register')
            except IntegrityError:
                return Response({'email': ['Email is already registered.']}, status=400)
            send_verification(user)
            return Response({'detail': 'Check your email to activate the account.'}, status=201)
        if operation == 'verify':
            try:
                payload = signing.loads(data.get('token', ''), salt='account-verification', max_age=86400)
                user = User.objects.get(pk=payload['id'], email=payload['email'])
            except (signing.BadSignature, User.DoesNotExist, KeyError):
                return Response({'detail': 'Invalid or expired token.'}, status=400)
            if user.suspended or (user.email_verified and not user.is_active):
                raise PermissionDenied('Account unavailable.')
            if not user.email_verified:
                user.email_verified = user.is_active = True
                user.save()
                record(user, 'account.verify')
            return Response({'detail': 'Email verified.'})
        if operation == 'resend':
            user = User.objects.filter(email__iexact=str(data.get('email', '')), email_verified=False, suspended=False).first()
            if user:
                send_verification(user)
            return Response({'detail': 'If eligible, a verification email has been sent.'})
        if operation == 'password-reset':
            form = PasswordResetForm(data)
            if not form.is_valid():
                return Response(form.errors, status=400)
            site = urlparse(settings.SITE_URL)
            form.save(use_https=site.scheme == 'https', domain_override=site.netloc,
                from_email=settings.DEFAULT_FROM_EMAIL, email_template_name='accounts/reset_email.txt', subject_template_name='accounts/reset_subject.txt')
            return Response({'detail': 'If eligible, password reset instructions have been sent.'})
        if operation == 'password-reset-confirm':
            try:
                user = User.objects.get(pk=urlsafe_base64_decode(data.get('uid', '')).decode())
            except (ValueError, TypeError, OverflowError, User.DoesNotExist):
                return Response({'detail': 'Invalid reset link.'}, status=400)
            if not default_token_generator.check_token(user, data.get('token', '')):
                return Response({'detail': 'Invalid or expired reset link.'}, status=400)
            form = SetPasswordForm(user, {'new_password1': data.get('password1'), 'new_password2': data.get('password2')})
            if not form.is_valid():
                return Response(form.errors, status=400)
            form.save()
            record(user, 'account.password.reset')
            return Response({'detail': 'Password reset.'})
        return Response({'detail': 'Unknown authentication operation.'}, status=404)

class UserViewSet(viewsets.GenericViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.none()

    @action(detail=False, methods=['get', 'patch'])
    def me(self, request):
        serializer = self.get_serializer(request.user, data=request.data, partial=True) if request.method == 'PATCH' else self.get_serializer(request.user)
        if request.method == 'PATCH':
            serializer.is_valid(raise_exception=True)
            serializer.save()
            record(request.user, 'account.profile.update')
        return Response(serializer.data)

class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ['id', 'name', 'description', 'created_by', 'created_at']
        read_only_fields = ['id', 'created_by', 'created_at']

class MemberInput(serializers.Serializer):
    email = serializers.EmailField()
    role = serializers.ChoiceField(choices=Membership.Role.choices, required=False, default='viewer')

class OrganizationViewSet(viewsets.ModelViewSet):
    serializer_class = OrganizationSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options', 'delete']

    def get_queryset(self):
        return visible_organizations(self.request.user) if self.request.user.is_authenticated else Organization.objects.none()

    def perform_create(self, serializer):
        serializer.instance = create_organization(self.request.user, **serializer.validated_data)

    def perform_update(self, serializer):
        if organization_role(self.request.user, serializer.instance) != 'admin':
            raise PermissionDenied()
        serializer.save()
        record(self.request.user, 'organization.update', serializer.instance)

    @extend_schema(responses={405: AuthResult})
    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Organization deletion is disabled. Archive projects and manage members instead.'}, status=405)

    @extend_schema(request=MemberInput, responses={200: None})
    @action(detail=True, methods=['get', 'post', 'delete'])
    def members(self, request, pk=None):
        org = self.get_object()
        if request.method == 'GET':
            return Response([{'id': m.pk, 'email': m.user.email, 'name': m.user.full_name, 'role': m.role} for m in org.memberships.select_related('user')])
        if organization_role(request.user, org) != 'admin':
            raise PermissionDenied()
        serializer = MemberInput(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = User.objects.filter(email__iexact=serializer.validated_data['email']).first()
        if not user:
            raise ValidationError('No eligible account found.')
        try:
            change_member(request.user, org, user, serializer.validated_data['role'], request.method == 'DELETE')
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response({'detail': 'Membership updated.'})

class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'owner', 'organization', 'target', 'archived', 'created_at', 'updated_at']
        read_only_fields = ['id', 'owner', 'archived', 'created_at', 'updated_at']

    def validate_organization(self, value):
        if self.instance and value != self.instance.organization:
            raise ValidationError('Moving projects across organizations is not supported.')
        if value and organization_role(self.context['request'].user, value) not in ['admin', 'editor']:
            raise ValidationError('Editor access to this organization is required.')
        return value

class FileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectFile
        fields = ['id', 'project', 'name', 'size', 'sha256', 'created_at']
        read_only_fields = fields

class ProjectViewSet(viewsets.ModelViewSet):
    serializer_class = ProjectSerializer
    http_method_names = ['get', 'post', 'patch', 'head', 'options', 'delete']

    def get_queryset(self):
        return visible_projects(self.request.user).select_related('organization', 'target')

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
        record(self.request.user, 'project.create', serializer.instance)

    def perform_update(self, serializer):
        if not can_edit(self.request.user, serializer.instance) or serializer.instance.archived:
            raise PermissionDenied()
        serializer.save()
        record(self.request.user, 'project.update', serializer.instance)

    @extend_schema(responses={405: AuthResult})
    def destroy(self, request, *args, **kwargs):
        return Response({'detail': 'Use the archive endpoint. Permanent deletion requires super-admin confirmation.'}, status=405)

    @extend_schema(request=inline_serializer('ArchiveProject', fields={'archived': serializers.BooleanField()}))
    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        project = self.get_object()
        if not can_manage(request.user, project):
            raise PermissionDenied()
        if type(request.data.get('archived')) is not bool:
            raise ValidationError({'archived': 'A boolean is required.'})
        project.archived = request.data['archived']
        project.save(update_fields=['archived', 'updated_at'])
        record(request.user, 'project.archive' if project.archived else 'project.restore', project)
        return Response(self.get_serializer(project).data)

    @extend_schema(methods=['GET'], responses={200: FileSerializer(many=True)})
    @extend_schema(methods=['POST'], request=inline_serializer('InputUpload', fields={'file': serializers.FileField()}), responses={201: FileSerializer})
    @action(detail=True, methods=['get', 'post'])
    def files(self, request, pk=None):
        project = self.get_object()
        if request.method == 'GET':
            return Response(FileSerializer(project.files.all(), many=True).data)
        upload = request.FILES.get('file')
        if not upload:
            raise ValidationError({'file': 'A file is required.'})
        try:
            item = store_input(request.user, project, upload)
        except DjangoValidationError as exc:
            raise ValidationError({'file': exc.messages})
        return Response(FileSerializer(item).data, status=201)

    @extend_schema(request=BuildRequestSerializer, responses={202: BuildRequestResult, 400: BuildRequestResult, 503: BuildRequestResult})
    @action(detail=True, methods=['post'])
    def build(self, request, pk=None):
        if not isinstance(request.data, dict):
            raise ValidationError('Expected an object containing pipeline and entrypoint.')
        pipeline = request.data.get('pipeline')
        entrypoint = request.data.get('entrypoint', 'model.py')
        if (pipeline is not None and not isinstance(pipeline, str)) or not isinstance(entrypoint, str):
            raise ValidationError('pipeline and entrypoint must be strings.')
        job = request_build(request.user, self.get_object(), pipeline, entrypoint)
        return Response({'id': str(job.pk), 'status': job.status, 'detail': job.reason},
                        status=202 if job.status == 'queued' else 400 if job.status == 'failed' else 503)

class FileViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = FileSerializer

    def get_queryset(self):
        return ProjectFile.objects.filter(project__in=visible_projects(self.request.user))

    @extend_schema(responses={(200, 'application/octet-stream'): OpenApiTypes.BINARY})
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        item = self.get_object()
        return FileResponse(item.file.open('rb'), as_attachment=True, filename=item.name, content_type='application/octet-stream')

class BuildSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuildJob
        fields = '__all__'

class BuildViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = BuildSerializer

    def get_queryset(self):
        return BuildJob.objects.filter(project__in=visible_projects(self.request.user))

    @extend_schema(responses={200: BuildLogSerializer(many=True)})
    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        return Response(list(self.get_object().logs.values('stage', 'level', 'message', 'created_at')))

    @extend_schema(responses={200: StageEvidenceSerializer(many=True)})
    @action(detail=True, methods=['get'])
    def stages(self, request, pk=None):
        return Response(list(self.get_object().stages.values('name', 'status', 'evidence')))

    @extend_schema(request=None, responses={200: BuildRequestResult, 400: None})
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        try:
            job = cancel_build(request.user, self.get_object())
        except DjangoValidationError as exc:
            raise ValidationError(exc.messages)
        return Response({'id': str(job.pk), 'status': job.status, 'detail': job.reason})

class ArtifactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Artifact
        exclude = ['file']

class ArtifactViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ArtifactSerializer

    def get_queryset(self):
        return Artifact.objects.filter(build__project__in=visible_projects(self.request.user))

    @extend_schema(responses={(200, 'application/octet-stream'): OpenApiTypes.BINARY})
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        item = self.get_object()
        return FileResponse(item.file.open('rb'), as_attachment=True, filename=item.name, content_type='application/octet-stream')

class TargetSerializer(serializers.ModelSerializer):
    class Meta:
        model = TargetProfile
        fields = '__all__'

class TargetViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TargetSerializer
    queryset = TargetProfile.objects.all().order_by('name')

class CapabilityAPI(APIView):
    serializer_class = serializers.Serializer

    @extend_schema(responses={200: None})
    def get(self, request, section=None):
        from django.conf import settings
        from compiler.inventory import current
        from compiler.hardware import fabulous_preflight, prototype_scope
        return Response({'platform_version': '0.2.0', 'stages': capabilities(),
                         'execution_enabled': settings.COMPILER_ENABLED, 'inventory': current(),
                         'pipeline': 'linear-int8-v1',
                         'pipelines': ['linear-int8-v1', 'linear-synth-v1', 'linear-fpga-v1', 'x2-candidate-v1', 'fabulous-reference-v1', 'zcu106-preflight-v1'],
                         'fabulous_preflight': fabulous_preflight(),
                         'prototype_scope': prototype_scope(),
                         'build_endpoint': '/api/v1/projects/{id}/build/'})

    @extend_schema(request=None, responses={501: None})
    def post(self, request, section=None):
        return Response({'status': 'unsupported', 'detail': 'Use a project build with linear-int8-v1, linear-synth-v1, x2-candidate-v1 or fabulous-reference-v1. Direct stage execution is unsupported. No tools ran.'}, status=501)

class StageCapabilityAPI(CapabilityAPI):
    @extend_schema(operation_id='compiler_stage_status', responses={200: None})
    def get(self, request, section=None):
        return super().get(request, section)

    @extend_schema(operation_id='compiler_stage_request', request=None, responses={501: None})
    def post(self, request, section=None):
        return super().post(request, section)

class ScopedRecords(viewsets.ReadOnlyModelViewSet):
    def get_queryset(self):
        if getattr(self, 'swagger_fake_view', False):
            return self.serializer_class.Meta.model.objects.none()
        return self.serializer_class.Meta.model.objects.filter(build__project__in=visible_projects(self.request.user)).order_by('pk')

class IRSerializer(serializers.ModelSerializer):
    class Meta:
        model = IRVersion
        fields = '__all__'

class IRViewSet(ScopedRecords):
    serializer_class = IRSerializer

class RTLSerializer(serializers.ModelSerializer):
    class Meta:
        model = RTLRevision
        fields = '__all__'

class RTLViewSet(ScopedRecords):
    serializer_class = RTLSerializer

class VerificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationRun
        fields = '__all__'

class VerificationViewSet(ScopedRecords):
    serializer_class = VerificationSerializer

class X2Serializer(serializers.ModelSerializer):
    class Meta:
        model = X2Configuration
        fields = '__all__'

class X2ViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = X2Serializer

    def get_queryset(self):
        return X2Configuration.objects.filter(project__in=visible_projects(self.request.user)).order_by('pk')
