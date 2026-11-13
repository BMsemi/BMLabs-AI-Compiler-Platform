import uuid
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower

class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError('Email is required.')
        user = self.model(email=email.strip().lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra.update(is_staff=True, is_superuser=True, is_active=True, email_verified=True)
        return self.create_user(email, password, **extra)

def avatar_path(instance, filename):
    return f'avatars/{instance.pk}/{uuid.uuid4().hex}.png'

class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=160)
    company = models.CharField(max_length=160, blank=True)
    contact = models.CharField(max_length=160, blank=True)
    avatar = models.ImageField(upload_to=avatar_path, blank=True)
    email_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    suspended = models.BooleanField(default=False)
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']
    objects = UserManager()

    class Meta:
        constraints = [models.UniqueConstraint(Lower('email'), name='unique_email_case_insensitive')]

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        if self.suspended:
            self.is_active = False
        super().save(*args, **kwargs)

    def get_full_name(self):
        return self.full_name or self.email

    def __str__(self):
        return self.email
