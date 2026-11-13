import tempfile
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core import mail, signing
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.tokens import default_token_generator
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from accounts.models import User
from accounts.services import verification_token
from organizations.models import Membership
from organizations.services import create_organization, change_member
from projects.models import Project, ProjectFile
from projects.services import store_input
from builds.models import BuildJob, Artifact, IRVersion, RTLRevision, VerificationRun
from builds.services import request_build
from compiler.contracts import GraphIR, TensorSpec, GraphNode
from compiler.models import TargetProfile, X2Configuration

PASSWORD = 'TeSt-Quartz-Orbit-9264!'

@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend', COMPILER_ENABLED=False)
class PlatformTests(TestCase):
    def setUp(self):
        cache.clear()
        self.media = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.addCleanup(self.media.cleanup)
        self.owner = User.objects.create_user('owner@example.com', PASSWORD, full_name='Project Owner', is_active=True, email_verified=True)
        self.outsider = User.objects.create_user('outsider@example.com', PASSWORD, full_name='Other User', is_active=True, email_verified=True)
        self.org = create_organization(self.owner, 'Lab A')
        self.project = Project.objects.create(name='Private model', owner=self.owner, organization=self.org)
        self.api = APIClient()
        self.api.force_authenticate(self.owner)
        self.client.force_login(self.owner)

    def test_registration_requires_verification(self):
        self.client.logout()
        response = self.client.post('/accounts/register/', {'email': 'New@Example.com', 'full_name': 'New Engineer', 'password1': PASSWORD, 'password2': PASSWORD})
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='new@example.com')
        self.assertFalse(user.is_active)
        self.assertTrue(user.check_password(PASSWORD))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/accounts/verify/', mail.outbox[0].body)
        self.assertFalse(self.client.login(username=user.email, password=PASSWORD))
        url = reverse('verify-email', args=[verification_token(user)])
        self.client.get(url)
        user.refresh_from_db()
        self.assertFalse(user.is_active)  # Email scanners cannot activate accounts.
        self.assertEqual(self.client.post(url).status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.email_verified and user.is_active)

    def test_expired_and_tampered_verification(self):
        token = verification_token(self.owner)
        self.assertEqual(self.client.post(reverse('verify-email', args=[token + 'tampered'])).status_code, 400)
        with patch('django.core.signing.time.time', return_value=timezone.now().timestamp() + 90000):
            self.assertEqual(self.client.post(reverse('verify-email', args=[token])).status_code, 400)

    def test_suspended_account_cannot_reactivate(self):
        self.owner.suspended = True
        self.owner.save()
        self.assertEqual(self.client.post(reverse('verify-email', args=[verification_token(self.owner)])).status_code, 403)
        self.assertFalse(self.client.login(username=self.owner.email, password=PASSWORD))

    def test_case_insensitive_login(self):
        self.client.logout()
        response = self.client.post('/accounts/login/', {'username': 'OWNER@EXAMPLE.COM', 'password': PASSWORD})
        self.assertEqual(response.status_code, 302)

    def test_password_reset_flow_and_reuse(self):
        self.client.post('/accounts/password-reset/', {'email': self.owner.email})
        self.assertEqual(len(mail.outbox), 1)
        uid = urlsafe_base64_encode(force_bytes(self.owner.pk))
        token = default_token_generator.make_token(self.owner)
        response = self.api.post('/api/v1/auth/password-reset-confirm/', {'uid': uid, 'token': token, 'password1': PASSWORD + 'New', 'password2': PASSWORD + 'New'})
        self.assertEqual(response.status_code, 200)
        self.owner.refresh_from_db()
        self.assertTrue(self.owner.check_password(PASSWORD + 'New'))
        self.assertFalse(default_token_generator.check_token(self.owner, token))

    def test_password_validation(self):
        self.client.logout()
        self.client.post('/accounts/register/', {'email': 'weak@example.com', 'full_name': 'Weak', 'password1': '123', 'password2': '123'})
        self.assertFalse(User.objects.filter(email='weak@example.com').exists())

    def test_auth_api_validates_payload_types(self):
        self.assertEqual(self.api.post('/api/v1/auth/login/', {'email': ['not', 'an', 'email'], 'password': {}}, format='json').status_code, 400)

    def test_login_throttled(self):
        self.client.logout()
        for _ in range(15):
            self.client.post('/accounts/login/', {'username': 'invalid@example.com', 'password': 'bad'})
        self.assertEqual(self.client.post('/accounts/login/', {'username': 'invalid@example.com', 'password': 'bad'}).status_code, 429)

    def test_api_login_requires_csrf_even_anonymous(self):
        client = APIClient(enforce_csrf_checks=True)
        self.assertEqual(client.post('/api/v1/auth/login/', {'email': self.owner.email, 'password': PASSWORD}).status_code, 403)
        token = client.get('/api/v1/auth/session/').json()['csrfToken']
        response = client.post('/api/v1/auth/login/', {'email': self.owner.email, 'password': PASSWORD}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(client.post('/api/v1/projects/', {'name': 'CSRF protected'}).status_code, 403)
        response = client.post('/api/v1/projects/', {'name': 'With CSRF'}, HTTP_X_CSRFTOKEN=response.json()['csrfToken'])
        self.assertEqual(response.status_code, 201)

    def test_cross_organization_isolation(self):
        self.api.force_authenticate(self.outsider)
        self.assertEqual(self.api.get('/api/v1/projects/').json()['count'], 0)
        self.assertEqual(self.api.get(f'/api/v1/projects/{self.project.pk}/').status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse('project-detail', args=[self.project.pk])).status_code, 404)

    def test_org_project_create_requires_editor(self):
        self.api.force_authenticate(self.outsider)
        response = self.api.post('/api/v1/projects/', {'name': 'Forbidden', 'organization': str(self.org.pk)})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Project.objects.filter(name='Forbidden').exists())

    def test_html_project_create_offers_organization(self):
        response = self.client.get('/projects/new/')
        self.assertContains(response, 'name="organization"')
        response = self.client.post('/projects/new/', {'name': 'Shared UI project', 'organization': str(self.org.pk)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Project.objects.get(name='Shared UI project').organization, self.org)

    def test_swagger_and_schema_available_to_authenticated_users(self):
        self.assertEqual(self.client.get('/api/swagger/').status_code, 200)
        self.assertEqual(self.client.get('/api/schema/').status_code, 200)

    def test_viewer_cannot_mutate(self):
        Membership.objects.create(user=self.outsider, organization=self.org, role='viewer')
        self.api.force_authenticate(self.outsider)
        url = f'/api/v1/projects/{self.project.pk}/'
        self.assertEqual(self.api.get(url).status_code, 200)
        self.assertEqual(self.api.patch(url, {'name': 'Hacked'}).status_code, 403)
        self.assertEqual(self.api.post(url + 'build/').status_code, 403)
        self.assertEqual(self.api.post(url + 'files/', {'file': SimpleUploadedFile('x.py', b'pass')}).status_code, 403)
        self.assertEqual(self.api.post(f'/api/v1/organizations/{self.org.pk}/members/', {'email': self.outsider.email, 'role': 'admin'}).status_code, 403)

    def test_editor_can_write_but_not_archive(self):
        Membership.objects.create(user=self.outsider, organization=self.org, role='editor')
        self.api.force_authenticate(self.outsider)
        url = f'/api/v1/projects/{self.project.pk}/'
        self.assertEqual(self.api.patch(url, {'name': 'Updated'}).status_code, 200)
        self.assertEqual(self.api.post(url + 'archive/', {'archived': True}, format='json').status_code, 403)

    def test_removed_owner_loses_org_project_access(self):
        Membership.objects.create(user=self.outsider, organization=self.org, role='admin')
        change_member(self.outsider, self.org, self.owner, remove=True)
        self.assertEqual(self.api.get(f'/api/v1/projects/{self.project.pk}/').status_code, 404)

    def test_last_admin_is_preserved(self):
        with self.assertRaises(ValidationError):
            change_member(self.owner, self.org, self.owner, remove=True)
        with self.assertRaises(ValidationError):
            change_member(self.owner, self.org, self.owner, 'viewer')
        self.assertTrue(Membership.objects.filter(organization=self.org, role='admin').exists())

    def test_personal_project_stays_private(self):
        private = Project.objects.create(name='Personal', owner=self.owner)
        Membership.objects.create(user=self.outsider, organization=self.org, role='admin')
        self.api.force_authenticate(self.outsider)
        self.assertEqual(self.api.get(f'/api/v1/projects/{private.pk}/').status_code, 404)

    def test_ownership_and_org_cannot_be_spoofed(self):
        response = self.api.post('/api/v1/projects/', {'name': 'Mine', 'owner': self.outsider.pk})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['owner'], self.owner.pk)
        response = self.api.patch(f'/api/v1/projects/{self.project.pk}/', {'organization': None}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_upload_download_and_digest(self):
        import hashlib
        content = b'print("hello")\n'
        response = self.api.post(f'/api/v1/projects/{self.project.pk}/files/', {'file': SimpleUploadedFile('model.py', content)})
        self.assertEqual(response.status_code, 201)
        item = ProjectFile.objects.get(pk=response.json()['id'])
        self.assertEqual(item.sha256, hashlib.sha256(content).hexdigest())
        self.assertNotIn('model.py', item.file.name)
        download = self.api.get(f'/api/v1/files/{item.pk}/download/')
        self.assertEqual(b''.join(download.streaming_content), content)
        self.assertIn('attachment', download['Content-Disposition'])
        self.api.force_authenticate(self.outsider)
        self.assertEqual(self.api.get(f'/api/v1/files/{item.pk}/download/').status_code, 404)
        self.assertEqual(self.client.get('/private-media/' + item.file.name).status_code, 404)

    def test_reject_unsafe_oversized_and_empty_uploads(self):
        for name, data in [('x.html', b'<script/>'), ('x.pkl', b'pickle'), ('x.py', b''), ('x.zip', b'zip')]:
            response = self.api.post(f'/api/v1/projects/{self.project.pk}/files/', {'file': SimpleUploadedFile(name, data)})
            self.assertEqual(response.status_code, 400)
        with override_settings(MAX_UPLOAD_BYTES=4):
            self.assertEqual(self.api.post(f'/api/v1/projects/{self.project.pk}/files/', {'file': SimpleUploadedFile('x.py', b'12345')}).status_code, 400)

    def test_build_request_is_honestly_blocked(self):
        store_input(self.owner, self.project, SimpleUploadedFile('input.py', b'x=1'))
        response = self.api.post(f'/api/v1/projects/{self.project.pk}/build/')
        self.assertEqual(response.status_code, 503)
        build = BuildJob.objects.get(pk=response.json()['id'])
        self.assertEqual(build.status, 'blocked')
        self.assertIsNone(build.started_at)
        self.assertIsNone(build.completed_at)
        self.assertEqual(len(build.input_manifest), 1)
        self.assertEqual(build.artifacts.count(), 0)
        self.assertEqual(build.logs.count(), 1)

    def test_build_input_and_target_snapshots_are_stable(self):
        target = TargetProfile.objects.create(name='Reference', version='1', resources={'count': 1})
        self.project.target = target
        self.project.save()
        x2 = X2Configuration.objects.create(project=self.project, abi_version='draft-1', contract={'precision': 8})
        build = request_build(self.owner, self.project)
        x2.contract = {'precision': 16}
        x2.save()
        target.resources = {'count': 99}
        target.save()
        store_input(self.owner, self.project, SimpleUploadedFile('later.py', b'x=1'))
        build.refresh_from_db()
        self.assertEqual(build.target_snapshot['resources'], {'count': 1})
        self.assertEqual(build.x2_snapshot['contract'], {'precision': 8})
        self.assertEqual(build.input_manifest, [])

    def test_build_and_artifact_isolation(self):
        build = request_build(self.owner, self.project)
        artifact = Artifact.objects.create(build=build, kind='report', name='report.txt', sha256='a'*64, file=SimpleUploadedFile('report.txt', b'report'))
        ir = IRVersion.objects.create(build=build, schema_version='1.0', graph={})
        verification = VerificationRun.objects.create(build=build, stage='V0')
        self.api.force_authenticate(self.outsider)
        for path in [f'builds/{build.pk}/', f'builds/{build.pk}/logs/', f'artifacts/{artifact.pk}/download/', f'ir/{ir.pk}/', f'verification/{verification.pk}/']:
            self.assertEqual(self.api.get('/api/v1/' + path).status_code, 404, path)

    def test_archive_blocks_mutations(self):
        url = f'/api/v1/projects/{self.project.pk}/'
        self.assertEqual(self.api.post(url + 'archive/', {'archived': True}, format='json').status_code, 200)
        self.assertEqual(self.api.patch(url, {'name': 'oops'}).status_code, 403)
        self.assertEqual(self.api.post(url + 'build/').status_code, 403)
        self.assertEqual(self.api.post(url + 'archive/', {'archived': False}, format='json').status_code, 200)

    def test_admin_and_operations_require_superuser(self):
        self.owner.is_staff = True
        self.owner.save()
        self.assertEqual(self.client.get('/admin/').status_code, 302)
        self.assertEqual(self.client.get('/operations/').status_code, 302)
        admin = User.objects.create_superuser('admin@example.com', PASSWORD, full_name='Administrator')
        self.client.force_login(admin)
        for path in ['/admin/', '/admin/accounts/user/', '/admin/accounts/user/add/', '/operations/']:
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_profile_cannot_escalate_privileges(self):
        self.api.patch('/api/v1/users/me/', {'is_superuser': True, 'is_staff': True, 'email': 'changed@example.com', 'full_name': 'Updated'})
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.is_superuser or self.owner.is_staff)
        self.assertEqual(self.owner.email, 'owner@example.com')
        self.assertEqual(self.owner.full_name, 'Updated')

    def test_all_dashboard_pages_render(self):
        job = request_build(self.owner, self.project)
        paths = ['/', '/projects/', '/projects/new/', f'/projects/{self.project.pk}/', f'/projects/{self.project.pk}/edit/',
                 '/organizations/', f'/organizations/{self.org.pk}/', '/workspace/', '/workspace/fabulous/', '/builds/',
                 f'/builds/{job.pk}/', '/accounts/profile/', '/api/docs/']
        for path in paths:
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_workspace_project_picker_preserves_access_boundaries(self):
        Project.objects.create(name='Hidden outsider project', owner=self.outsider)
        Project.objects.create(name='Archived model', owner=self.owner, archived=True)
        response = self.client.get('/workspace/rtl/')
        self.assertContains(response, 'Private model')
        self.assertNotContains(response, 'Hidden outsider project')
        self.assertNotContains(response, 'Archived model')
        self.client.force_login(self.outsider)
        response = self.client.get('/workspace/rtl/')
        self.assertContains(response, 'Hidden outsider project')
        self.assertNotContains(response, 'Private model')

    def test_logout_is_post_only_and_protected(self):
        self.assertEqual(self.client.get('/accounts/logout/').status_code, 405)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post('/accounts/logout/').status_code, 403)

    def test_api_requires_authentication(self):
        self.api.force_authenticate(None)
        for endpoint in ['projects', 'builds', 'organizations', 'compiler', 'fabulous/targets', 'ir', 'rtl', 'verification', 'x2/configurations']:
            self.assertEqual(self.api.get(f'/api/v1/{endpoint}/').status_code, 403)

    def test_compiler_endpoints_do_not_claim_success(self):
        self.assertFalse(self.api.get('/api/v1/compiler/').json()['execution_enabled'])
        self.assertEqual(self.api.post('/api/v1/compiler/rtl/').status_code, 501)

    def test_security_headers(self):
        response = self.client.get('/')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertIn("frame-ancestors 'none'", response['Content-Security-Policy'])

    def test_profile_avatar_validation(self):
        response = self.client.post('/accounts/profile/', {'full_name': 'Owner', 'avatar': SimpleUploadedFile('fake.png', b'not an image', content_type='image/png')})
        self.assertEqual(response.status_code, 200)
        self.owner.refresh_from_db()
        self.assertFalse(self.owner.avatar)

class IRContractTests(TestCase):
    def test_valid_graph(self):
        GraphIR((TensorSpec('x', (1, 8), 'int8'),), (TensorSpec('y', (1, 8), 'int8'),), (GraphNode('n1', 'relu', ('x',), ('y',)),)).validate()

    def test_invalid_shape_type_and_undefined_inputs(self):
        for tensor in [TensorSpec('x', (-1,), 'int8'), TensorSpec('x', (1,), 'unknown')]:
            with self.assertRaises(ValueError):
                GraphIR((tensor,), (), ()).validate()
        with self.assertRaises(ValueError):
            GraphIR((), (), (GraphNode('n', 'relu', ('missing',), ('y',)),)).validate()

    def test_duplicate_outputs_and_unknown_schema(self):
        with self.assertRaises(ValueError):
            GraphIR((TensorSpec('x', (1,), 'int8'),), (), (GraphNode('n', 'relu', ('x',), ('x',)),)).validate()
        with self.assertRaises(ValueError):
            GraphIR((), (), (), schema_version='99').validate()
