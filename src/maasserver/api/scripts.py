# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""API handlers: `Script`."""

__all__ = [
    'NodeScriptHandler',
    'NodeScriptsHandler',
    ]

from base64 import b64encode
from email.utils import format_datetime

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from formencode.validators import (
    Bool,
    Int,
    String,
)
from maasserver.api.support import (
    admin_method,
    operation,
    OperationsHandler,
)
from maasserver.api.utils import (
    get_mandatory_param,
    get_optional_param,
)
from maasserver.exceptions import MAASAPIValidationError
from maasserver.forms.script import ScriptForm
from metadataserver.enum import SCRIPT_TYPE
from metadataserver.models import Script
from piston3.utils import rc


class NodeScriptsHandler(OperationsHandler):
    """Manage custom scripts.

    This functionality is only available to administrators.
    """
    api_doc_section_name = "Node Scripts"

    update = delete = None

    @classmethod
    def resource_uri(cls):
        return ('scripts_handler', [])

    @admin_method
    def create(self, request):
        """Create a new script.

        :param name: The name of the script.
        :type name: unicode

        :param title: The title of the script.
        :type title: unicode

        :param description: A description of what the script does.
        :type description: unicode

        :param tags: A comma seperated list of tags for this script.
        :type tags: unicode

        :param type: The script_type defines when the script should be used.
            Can be testing or commissioning, defaults to testing.
        :type script_type: unicode

        :param timeout: How long the script is allowed to run before failing.
            0 gives unlimited time, defaults to 0.
        :type timeout: unicode

        :param destructive: Whether or not the script overwrites data on any
            drive on the running system. Destructive scripts can not be run on
            deployed systems. Defaults to false.
        :type destructive: boolean

        :param script: The content of the script to be uploaded in binary form.
            note: this is not a normal parameter, but a file upload. Its
            filename is ignored; MAAS will know it by the name you pass to the
            request. Optionally you can ignore the name and script parameter in
            favor of uploading a single file as part of the request.

        :param comment: A comment about what this change does.
        :type comment: unicode
        """
        if 'script' in request.FILES:
            request.data['script'] = request.FILES.get('script').read()
        elif len(request.FILES) == 1:
            for name, script in request.FILES.items():
                request.data['name'] = name
                request.data['script'] = script.read()
        form = ScriptForm(data=request.data)
        if form.is_valid():
            return form.save()
        else:
            raise MAASAPIValidationError(form.errors)

    def read(self, request):
        """Return a list of stored scripts.

        :param type: Only return scripts with the given type. This can be
            testing or commissioning. Defaults to showing both.
        :type script_type: unicode

        :param include_script: Include the base64 encoded script content.
        :type include_script: bool

        :param filters: A comma seperated list to show only results
                        with a script name or tag.
        :type filters: unicode
        """
        qs = Script.objects.all()

        script_type = get_optional_param(request.GET, 'type')
        if script_type is not None:
            if script_type.isdigit():
                script_type = int(script_type)
            elif script_type in ['test', 'testing']:
                script_type = SCRIPT_TYPE.TESTING
            elif script_type in ['commission', 'commissioning']:
                script_type = SCRIPT_TYPE.COMMISSIONING
            else:
                raise MAASAPIValidationError('Unknown script type')
            qs = qs.filter(script_type=script_type)

        include_script = get_optional_param(
            request.GET, 'include_script', False, Bool)
        filters = get_optional_param(request.GET, 'filters', None, String)
        if filters is not None:
            filters = set(filters.split(','))

        ret = []
        for script in qs:
            if (filters is not None and script.name not in filters and
                    filters.isdisjoint(script.tags)):
                continue
            else:
                script.include_script = include_script
                ret.append(script)

        return ret


class NodeScriptHandler(OperationsHandler):
    """Manage or view a custom script.
    """
    api_doc_section_name = "Node Script"

    fields = (
        'id',
        'name',
        'title',
        'description',
        'tags',
        'type',
        'type_name',
        'timeout',
        'destructive',
        'history',
        'default',
    )
    model = Script

    create = None

    @classmethod
    def resource_uri(cls, script=None):
        # See the comment in NodeHandler.resource_uri
        script_name = 'name'
        if script is not None:
            script_name = script.name
        return ('script_handler', (script_name, ))

    @classmethod
    def type(handler, script):
        return script.script_type

    @classmethod
    def type_name(handler, script):
        return script.script_type_name

    @classmethod
    def history(handler, script):
        results = []
        for script_ver in script.script.previous_versions():
            version = {
                'id': script_ver.id,
                'comment': script_ver.comment,
                'created': format_datetime(script_ver.created),
            }
            if getattr(script, 'include_script', False):
                version['data'] = b64encode(script_ver.data.encode())
            results.append(version)
        return results

    def read(self, request, name):
        """Return a script's metadata.

        :param include_script: Include the base64 encoded script content.
        :type include_script: bool
        """
        if name.isdigit():
            script = get_object_or_404(Script, id=int(name))
        else:
            script = get_object_or_404(Script, name=name)
        script.include_script = get_optional_param(
            request.GET, 'include_script', False, Bool)
        return script

    @admin_method
    def delete(self, request, name):
        """Delete a script."""
        if name.isdigit():
            script = get_object_or_404(Script, id=int(name))
        else:
            script = get_object_or_404(Script, name=name)

        if script.default:
            raise MAASAPIValidationError("Unable to delete default script")

        script.delete()
        return rc.DELETED

    @admin_method
    def update(self, request, name):
        """Update a commissioning script.

        :param name: The name of the script.
        :type name: unicode

        :param title: The title of the script.
        :type title: unicode

        :param description: A description of what the script does.
        :type description: unicode

        :param tags: A comma seperated list of tags for this script.
        :type tags: unicode

        :param type: The type defines when the script should be used. Can be
            testing or commissioning, defaults to testing.
        :type script_type: unicode

        :param timeout: How long the script is allowed to run before failing.
            0 gives unlimited time, defaults to 0.
        :type timeout: unicode

        :param destructive: Whether or not the script overwrites data on any
            drive on the running system. Destructive scripts can not be run on
            deployed systems. Defaults to false.
        :type destructive: boolean

        :param script: The content of the script to be uploaded in binary form.
            note: this is not a normal parameter, but a file upload. Its
            filename is ignored; MAAS will know it by the name you pass to the
            request. Optionally you can ignore the name and script parameter in
            favor of uploading a single file as part of the request.

        :param comment: A comment about what this change does.
        :type comment: unicode
        """
        if name.isdigit():
            script = get_object_or_404(Script, id=int(name))
        else:
            script = get_object_or_404(Script, name=name)

        if 'script' in request.FILES:
            request.data['script'] = request.FILES.get('script').read()
        elif len(request.FILES) == 1:
            for name, script_content in request.FILES.items():
                request.data['name'] = name
                request.data['script'] = script_content.read()

        form = ScriptForm(instance=script, data=request.data)
        if form.is_valid():
            return form.save()
        else:
            raise MAASAPIValidationError(form.errors)

    @operation(idempotent=True)
    def download(self, request, name):
        """Download a script.

        :param revision: What revision to download, latest by default. Can use
            rev as a shortcut.
        :type revision: integer
        """
        if name.isdigit():
            script = get_object_or_404(Script, id=int(name))
        else:
            script = get_object_or_404(Script, name=name)
        revision = get_optional_param(request.GET, 'revision', None, Int)
        if revision is None:
            revision = get_optional_param(request.GET, 'rev', None, Int)
        if revision is not None:
            for rev in script.script.previous_versions():
                if rev.id == revision:
                    return HttpResponse(
                        rev.data, content_type='application/binary')
            raise MAASAPIValidationError("%s not found in history" % revision)
        else:
            return HttpResponse(
                script.script.data, content_type='application/binary')

    @admin_method
    @operation(idempotent=False)
    def revert(self, request, name):
        """Revert a script to an earlier version.

        :param to: What revision in the script's history to revert to. This can
            either be an ID or a negative number representing how far back to
            go.
        :type to: integer

        Returns 404 if the script is not found.
        """
        revert_to = get_mandatory_param(request.data, 'to', Int)

        if name.isdigit():
            script = get_object_or_404(Script, id=int(name))
        else:
            script = get_object_or_404(Script, name=name)
        try:
            if script.default:
                raise MAASAPIValidationError("Unable to revert default script")

            def gc_hook(value):
                script.script = value
                script.save()
            script.script.revert(revert_to, gc_hook=gc_hook)
            return script
        except ValueError as e:
            raise MAASAPIValidationError(e.args[0])

    @admin_method
    @operation(idempotent=False)
    def add_tag(self, request, name):
        """Add a single tag to a script.

        :param tag: The tag being added.
        :type tag: unicode

        Returns 404 if the script is not found.
        """
        tag = get_mandatory_param(request.data, 'tag', String)

        if ',' in tag:
            raise MAASAPIValidationError('Tag may not contain a ",".')

        if name.isdigit():
            script = get_object_or_404(Script, id=int(name))
        else:
            script = get_object_or_404(Script, name=name)

        script.add_tag(tag)
        script.save()
        return script

    @admin_method
    @operation(idempotent=False)
    def remove_tag(self, request, name):
        """Remove a single tag to a script.

        :param tag: The tag being removed.
        :type tag: unicode

        Returns 404 if the script is not found.
        """
        tag = get_mandatory_param(request.data, 'tag', String)

        if name.isdigit():
            script = get_object_or_404(Script, id=int(name))
        else:
            script = get_object_or_404(Script, name=name)

        script.remove_tag(tag)
        script.save()
        return script
