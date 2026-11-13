import tempfile

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User
from builds.models import Artifact, BuildJob
from projects.models import Project


@override_settings(SECURE_SSL_REDIRECT=False, STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class MediaPlaybackTests(TestCase):
    def setUp(self):
        self.media = tempfile.TemporaryDirectory()
        self.addCleanup(self.media.cleanup)
        override = override_settings(MEDIA_ROOT=self.media.name)
        override.enable()
        self.addCleanup(override.disable)
        self.owner = User.objects.create_user('media-owner@example.com', is_active=True, email_verified=True)
        self.other = User.objects.create_user('media-other@example.com', is_active=True, email_verified=True)
        project = Project.objects.create(name='Media test', owner=self.owner)
        self.job = BuildJob.objects.create(project=project, requested_by=self.owner)
        self.artifact = Artifact.objects.create(build=self.job, name='demo.mp4', kind='report',
            file=ContentFile(b'0123456789', name='demo.mp4'), metadata={'chapters': [{'start': 0, 'title': 'Start'}]})
        self.url = reverse('artifact-stream', args=[self.artifact.pk])
        self.watch = reverse('artifact-watch', args=[self.artifact.pk])
        self.client.force_login(self.owner)

    def test_full_stream_and_head(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b''.join(response.streaming_content), b'0123456789')
        response.close()
        self.assertEqual(response['Content-Type'], 'video/mp4')
        self.assertEqual(response['Content-Disposition'], 'inline')
        self.assertEqual(response['Accept-Ranges'], 'bytes')
        self.assertIn('no-store', response['Cache-Control'])
        response = self.client.head(self.url)
        self.assertEqual(response['Content-Length'], '10')
        self.assertEqual(response.content, b'')

    def test_ranges(self):
        for header, data, content_range in [
            ('bytes=2-4', b'234', 'bytes 2-4/10'),
            ('bytes=7-', b'789', 'bytes 7-9/10'),
            ('bytes=-3', b'789', 'bytes 7-9/10'),
            ('bytes=8-99', b'89', 'bytes 8-9/10'),
        ]:
            with self.subTest(header=header):
                response = self.client.get(self.url, HTTP_RANGE=header)
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response['Content-Range'], content_range)
                self.assertEqual(response['Content-Length'], str(len(data)))
                self.assertEqual(b''.join(response.streaming_content), data)
                response.close()

    def test_unsatisfiable_and_malformed_ranges(self):
        for header in ['bytes=10-', 'bytes=5-2', 'bytes=-0']:
            response = self.client.get(self.url, HTTP_RANGE=header)
            self.assertEqual(response.status_code, 416)
            self.assertEqual(response['Content-Range'], 'bytes */10')
        for header in ['bytes=oops', 'bytes=0-1,4-5']:
            response = self.client.get(self.url, HTTP_RANGE=header)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(b''.join(response.streaming_content), b'0123456789')
            response.close()

    def test_access_control_for_player_and_media(self):
        self.client.logout()
        for url in [self.watch, self.url]:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.other)
        for url in [self.watch, self.url]:
            self.assertEqual(self.client.get(url).status_code, 404)

    def test_player_and_captions(self):
        caption = Artifact.objects.create(build=self.job, name='demo.vtt', kind='report',
            file=ContentFile(b'WEBVTT\n', name='demo.vtt'))
        response = self.client.get(self.watch)
        self.assertContains(response, 'Play with voice-over')
        self.assertContains(response, reverse('artifact-stream', args=[caption.pk]))
        self.assertContains(response, 'data-time="0"')
        self.artifact.metadata = {'chapters': 30}
        self.artifact.save(update_fields=['metadata'])
        self.assertEqual(self.client.get(self.watch).status_code, 200)

    def test_unsupported_content_and_missing_file(self):
        self.artifact.name = 'untrusted.html'
        self.artifact.save(update_fields=['name'])
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.client.get(self.watch).status_code, 404)
        self.artifact.name = 'demo.mp4'
        self.artifact.save(update_fields=['name'])
        self.artifact.file.storage.delete(self.artifact.file.name)
        self.assertEqual(self.client.get(self.url).status_code, 404)
