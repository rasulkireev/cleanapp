from allauth.account.forms import LoginForm, SignupForm
from django import forms
from datetime import datetime
import pytz
from functools import lru_cache

from core.models import Profile, Sitemap
from core.utils import DivErrorList


@lru_cache(maxsize=1)
def get_timezone_list():
    timezones = []
    now = datetime.now(pytz.UTC)

    for tz_name in pytz.common_timezones:
        try:
            tz = pytz.timezone(tz_name)
            dt = now.astimezone(tz)
            offset = dt.strftime('%z')
            offset_hours = f"{offset[:3]}:{offset[3:]}"
            label = f"(UTC{offset_hours}) {tz_name.replace('_', ' ')}"
            timezones.append({'value': tz_name, 'label': label})
        except Exception:
            timezones.append({'value': tz_name, 'label': tz_name})

    return sorted(timezones, key=lambda x: x['label'])


class CustomSignUpForm(SignupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_class = DivErrorList


class CustomLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_class = DivErrorList


class ProfileUpdateForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30, required=False)
    last_name = forms.CharField(max_length=30, required=False)

    class Meta:
        model = Profile
        fields = ['preferred_email_time', 'timezone']
        widgets = {
            'preferred_email_time': forms.TimeInput(attrs={'type': 'time'}),
            'timezone': forms.TextInput(attrs={
                'list': 'timezone-list',
                'autocomplete': 'off'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        if commit:
            user.save()
            profile.save()
        return profile


class SitemapForm(forms.ModelForm):
    class Meta:
        model = Sitemap
        fields = ['sitemap_url']
        widgets = {
            'sitemap_url': forms.URLInput(attrs={
                'class': 'block mt-1 w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
                'placeholder': 'https://example.com/sitemap.xml'
            })
        }
        labels = {
            'sitemap_url': 'Sitemap URL'
        }


class SitemapSettingsForm(forms.ModelForm):
    class Meta:
        model = Sitemap
        fields = ['pages_per_review', 'review_cadence']
        widgets = {
            'pages_per_review': forms.NumberInput(attrs={
                'class': 'block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm',
                'min': '1',
                'max': '50'
            }),
            'review_cadence': forms.Select(attrs={
                'class': 'block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm'
            })
        }
        labels = {
            'pages_per_review': 'Pages per review email',
            'review_cadence': 'Review cadence'
        }
