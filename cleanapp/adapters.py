from allauth.account.adapter import DefaultAccountAdapter


class CustomAccountAdapter(DefaultAccountAdapter):
    def send_mail(self, template_prefix, email, context):
        if template_prefix == "account/email/unknown_account":
            return
        return super().send_mail(template_prefix, email, context)
