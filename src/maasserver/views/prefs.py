# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Preferences views."""

__all__ = [
    'userprefsview',
    ]

from django.contrib import messages
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import PermissionDenied
from django.core.urlresolvers import reverse
from django.shortcuts import (
    get_object_or_404,
    render_to_response,
)
from django.template import RequestContext
from django.views.generic import CreateView
from maasserver.forms import (
    ProfileForm,
    SSLKeyForm,
)
from maasserver.models import SSLKey
from maasserver.views import (
    HelpfulDeleteView,
    process_form,
)


class SSLKeyCreateView(CreateView):

    form_class = SSLKeyForm
    template_name = 'maasserver/prefs_add_sslkey.html'

    def get_form_kwargs(self):
        kwargs = super(SSLKeyCreateView, self).get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.info(self.request, "SSL key added.")
        return super(SSLKeyCreateView, self).form_valid(form)

    def get_success_url(self):
        return reverse('prefs')


class SSLKeyDeleteView(HelpfulDeleteView):

    template_name = 'maasserver/prefs_confirm_delete_sslkey.html'
    context_object_name = 'sslkey'
    model = SSLKey

    def get_object(self):
        keyid = self.kwargs.get('keyid', None)
        key = get_object_or_404(SSLKey, id=keyid)
        if key.user != self.request.user:
            raise PermissionDenied("Can't delete this key.  It's not yours.")
        return key

    def get_next_url(self):
        return reverse('prefs')


def userprefsview(request):
    user = request.user
    # Process the profile update form.
    profile_form, response = process_form(
        request, ProfileForm, reverse('prefs'), 'profile', "Profile updated.",
        {'instance': user})
    if response is not None:
        return response

    # Process the password change form.
    password_form, response = process_form(
        request, PasswordChangeForm, reverse('prefs'), 'password',
        "Password updated.", {'user': user})
    if response is not None:
        return response

    return render_to_response(
        'maasserver/prefs.html',
        {
            'profile_form': profile_form,
            'password_form': password_form,
        },
        context_instance=RequestContext(request))
