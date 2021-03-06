/* Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * OS/Release seletion utilities.
 *
 * @module Y.maas.power_parameter
 */

YUI.add('maas.os_distro_select', function(Y) {

Y.log('loading maas.os_distro_select');
var module = Y.namespace('maas.os_distro_select');

// Only used to mockup io in tests.
module._io = new Y.maas.io.getIO();

var OSReleaseWidget;

/**
 * A widget class that modifies the viewable options of the release
 * field, based on the selected operating system field.
 *
 */
OSReleaseWidget = function() {
    OSReleaseWidget.superclass.constructor.apply(this, arguments);
};

OSReleaseWidget.NAME = 'os-release-widget';

Y.extend(OSReleaseWidget, Y.Widget, {

   /**
    * Initialize the widget.
    * - cfg.srcNode is the node which will be updated when the selected
    *   value of the 'os node' will change.
    * - cfg.osNode is the node containing a 'select' element.  When
    *   the selected element will change, the srcNode HTML will be
    *   updated.
    *
    * @method initializer
    */
    initializer: function(cfg) {
        this.initialSkip = true;
    },

   /**
    * Bind the widget to events (to name 'event_name') generated by the given
    * 'osNode'.
    *
    * @method bindTo
    */
    bindTo: function(osNode, event_name) {
        var self = this;
        Y.one(osNode).on(event_name, function(e) {
            var osValue = e.currentTarget.get('value');
            self.switchTo(osValue);
        });
        var osValue = Y.one(osNode).get('value');
        self.switchTo(osValue);
    },

   /**
    * React to a new value of the os node: update the HTML of
    * 'srcNode'.
    *
    * @method switchTo
    */
    switchTo: function(newOSValue) {
        var srcNode = this.get('srcNode');
        var options = srcNode.all('option');
        var selected = false;
        options.each(function(option) {
            var sel = this.modifyOption(option, newOSValue);
            if (selected === false) {
                selected = sel;
            }
        }, this);

        // We skip selection on first load, as Django will already
        // provide the users, current selection. Without this the
        // current selection will be clobered.
        if (this.initialSkip === true) {
            this.initialSkip = false;
            return;
        }

        // See if a selection was made, if not then we need
        // to select the first visible as a default is not
        // present.
        if(!selected) {
            this.selectVisableOption(options);
        }
    },

   /**
    * Modify an option to make it visible or hidden. Returns true
    * if the method also make the selection active.
    *
    * @method modifyOption
    */
    modifyOption: function(option, newOSValue) {
        var selected = false;
        var value = option.get('value');
        var split_value = value.split("/");

        // If "Default OS" is selected, then
        // only show "Default OS Release".
        if(newOSValue === '') {
            if(value === '') {
                option.removeClass('hidden');
                option.set('selected', 'selected');
            }
            else {
                option.addClass('hidden');
            }
        }
        else {
            if(split_value[0] === newOSValue) {
                option.removeClass('hidden');
                if(split_value[1] === '' && !this.initialSkip) {
                    selected = true;
                    option.set('selected', 'selected');
                }
            }
            else {
                option.addClass('hidden');
            }
        }
        return selected;
    },

   /**
    * Selected the first option that is not hidden.
    *
    * @method selectVisableOption
    */
    selectVisableOption: function(options) {
        var first_option = null;
        Y.Array.each(options, function(option) {
            if(!option.hasClass('hidden')) {
                if(first_option === null) {
                    first_option = option;
                }
            }
        });
        if(first_option !== null) {
            first_option.set('selected', 'selected');
        }
    }
});

module.OSReleaseWidget = OSReleaseWidget;

}, '0.1', {'requires': ['widget', 'maas.io']}
);

YUI().use(
  'maas.os_distro_select',
  function (Y) {
  Y.on('load', function() {
    // Create OSDistroWidget so that the release field will be
    // updated each time the value of the os field changes.
    var releaseWidget = new Y.maas.os_distro_select.OSReleaseWidget({
        srcNode: '#id_deploy-default_distro_series'
        });
    releaseWidget.bindTo(Y.one('#id_deploy-default_osystem'), 'change');
    releaseWidget.render();
  });
});
