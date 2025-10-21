from allauth.account.forms import LoginForm, SignupForm
from django import forms

from core.models import Profile, Sitemap
from core.utils import DivErrorList


class CustomSignUpForm(SignupForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_class = DivErrorList


class CustomLoginForm(LoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.error_class = DivErrorList


class ProfileUpdateForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30)
    last_name = forms.CharField(max_length=30)
    email = forms.EmailField()

    class Meta:
        model = Profile
        fields = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields["first_name"].initial = self.instance.user.first_name
            self.fields["last_name"].initial = self.instance.user.last_name
            self.fields["email"].initial = self.instance.user.email

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data["email"]
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
