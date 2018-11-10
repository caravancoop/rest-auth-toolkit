from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth import password_validation
from django.core import exceptions
from django.utils.translation import gettext as _

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from .utils import get_object_from_setting

try:
    import facepy
except ImportError:
    facepy = None


User = get_user_model()
EmailConfirmation = get_object_from_setting('email_confirmation_class')


class SignupDeserializer(serializers.ModelSerializer):
    """Deserializer to create users without username."""

    class Meta:
        model = User
        fields = ('email', 'password')
        extra_kwargs = {
            'password': {'style': {'input_type': 'password'}},
        }

    def validate(self, data):
        password = data['password']

        # Create user object without saving it to get extra checks by validators
        user = User(**data)

        errors = {}
        try:
            password_validation.validate_password(password=password, user=user)
        except exceptions.ValidationError as e:
            errors['password'] = list(e.messages)

        if errors:
            raise serializers.ValidationError(errors)

        return data

    def create(self, validated_data):
        return User.objects.create_user(
            email=validated_data['email'],
            password=validated_data['password'],
            is_active=False,
        )


class EmailConfirmationDeserializer(serializers.Serializer):
    email = serializers.EmailField()
    token = serializers.CharField()

    def validate(self, data):
        msg = None

        try:
            confirmation = EmailConfirmation.objects.get(
                external_id=data['token'],
                user__email=data['email'],
            )
            confirmation.confirm()
        except EmailConfirmation.DoesNotExist:
            msg = _('Invalid link')
        except EmailConfirmation.IsExpired:
            # FIXME it's not possible to register with the same email
            msg = _('Email expired, please register again')

        if msg:
            raise ValidationError({'errors': [msg]})

        return {'user': confirmation.user}


class LoginDeserializer(serializers.Serializer):
    """Deserializer to find a user from credentials."""

    email = serializers.EmailField()
    password = serializers.CharField(style={'input_type': 'password'})

    def validate(self, data):
        user = authenticate(email=data['email'], password=data['password'])

        if user is None:
            msg = _('Invalid email or password')
            raise ValidationError({'errors': [msg]})

        return {'user': user}


class FacebookLoginDeserializer(serializers.Serializer):
    """Deserializer to create users from client-side Facebook auth response."""

    signed_request = serializers.CharField()

    def validate(self, data):
        req = facepy.SignedRequest(data['signed_request'],
                                   settings.FACEBOOK_APP_SECRET_KEY,
                                   settings.FACEBOOK_APP_ID)

        # XXX handle facebook exceptions
        # for example, the user can refuse to share their email address

        graph = facepy.GraphAPI(req.user.oauth_token.token)
        data = graph.get('me?fields=email,first_name,last_name,third_party_id')

        extended_token, __ = facepy.get_extended_access_token(
            req.user.oauth_token.token,
            settings.FACEBOOK_APP_ID, settings.FACEBOOK_APP_SECRET_KEY)

        user = User.objects.get_or_create_facebook_user(data, extended_token)[0]

        return {'user': user}
