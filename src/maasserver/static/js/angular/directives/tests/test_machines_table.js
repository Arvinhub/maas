/* Copyright 2017 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Unit tests for machines table directive.
 */

describe("maasMachinesTable", function() {

    // Load the MAAS module.
    beforeEach(module("MAAS"));

    // Preload the $templateCache with empty contents. We only test the
    // controller of the directive, not the template.
    var $q, $templateCache;
    beforeEach(inject(function($injector) {
        $q = $injector.get('$q');
        $templateCache = $injector.get('$templateCache');
        $templateCache.put(
            "static/partials/machines-table.html?v=undefined", '');
    }));

    // Load the required managers.
    var MachinesManager, GeneralManager, ManagerHelperService;
    beforeEach(inject(function($injector) {
        MachinesManager = $injector.get('MachinesManager');
        GeneralManager = $injector.get('GeneralManager');
        ManagerHelperService = $injector.get('ManagerHelperService');
    }));

    // Create a new scope before each test.
    var $scope;
    beforeEach(inject(function($rootScope) {
        $scope = $rootScope.$new();
    }));

    // Makes a machine.
    function makeMachine() {
        var machine = {
            system_id: makeName("system_id"),
            $selected: false
        };
        MachinesManager._items.push(machine);
        return machine;
    }

    // Return the compiled directive with the items from the scope.
    function compileDirective(design) {
        var directive;
        var html = [
            '<div>',
                '<maas-machines-table ',
                  'on-listing-change="onListingChange($machines)" ',
                  'on-check-all="onCheckAll()" ',
                  'on-check="onCheck($machine)"></maas-machines-table>',
            '</div>'
            ].join('');

        // Compile the directive.
        inject(function($compile) {
            directive = $compile(html)($scope);
        });

        // Perform the digest cycle to finish the compile.
        $scope.$digest();
        return directive.find("maas-machines-table");
    }

    it("sets initial variables", function() {
        var directive = compileDirective();
        var scope = directive.isolateScope();
        expect(scope.table).toEqual({
          column: 'fqdn',
          predicate: 'fqdn',
          reverse: false,
          allViewableChecked: false
        });
        expect(scope.machines).toBe(MachinesManager.getItems());
        expect(scope.filteredMachines).toEqual([]);
        expect(scope.osinfo).toBe(GeneralManager.getData("osinfo"));
    });

    it("polls for osinfo once loaded", function() {
        spyOn(GeneralManager, "startPolling");
        var managerDefer = $q.defer();
        spyOn(ManagerHelperService, "loadManager").and.returnValue(
            managerDefer.promise);

        var directive = compileDirective();
        var scope = directive.isolateScope();

        managerDefer.resolve();
        $scope.$digest();
        expect(GeneralManager.startPolling).toHaveBeenCalledWith(
            scope, "osinfo");
    });

    it("stops polling on scope destroy", function() {
        spyOn(GeneralManager, "stopPolling");
        var directive = compileDirective();
        var scope = directive.isolateScope();

        $scope.$destroy();
        expect(GeneralManager.stopPolling).toHaveBeenCalledWith(
            scope, "osinfo");
    });

    describe("updateAllChecked", function() {

        it("sets allViewableChecked to false when no machines", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            scope.table.allViewableChecked = true;
            scope.filteredMachines = [];
            scope.updateAllChecked();
            expect(scope.table.allViewableChecked).toBe(false);
        });

        it("sets allViewableChecked to false when one not selected",
            function() {
                var directive = compileDirective();
                var scope = directive.isolateScope();
                scope.table.allViewableChecked = true;
                scope.filteredMachines = [{
                    $selected: true
                }, {
                    $selected: false
                }];
                scope.updateAllChecked();
                expect(scope.table.allViewableChecked).toBe(false);
            });

        it("sets allViewableChecked to false when one not selected",
            function() {
                var directive = compileDirective();
                var scope = directive.isolateScope();
                scope.filteredMachines = [{
                    $selected: true
                }, {
                    $selected: true
                }];
                scope.updateAllChecked();
                expect(scope.table.allViewableChecked).toBe(true);
            });
    });

    describe("toggleCheckAll", function() {

        it("unselected all selected machines", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var machine = makeMachine();
            MachinesManager.selectItem(machine.system_id);
            scope.table.allViewableChecked = true;
            scope.filteredMachines = [machine];
            scope.toggleCheckAll();
            expect(machine.$selected).toBe(false);
            expect(scope.table.allViewableChecked).toBe(false);
        });

        it("selects all unselected machines", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var machine = makeMachine();
            scope.table.allViewableChecked = false;
            scope.filteredMachines = [machine];
            scope.toggleCheckAll();
            expect(machine.$selected).toBe(true);
            expect(scope.table.allViewableChecked).toBe(true);
        });

        it("calls onCheckAll", function() {
            $scope.onCheckAll = jasmine.createSpy("onCheckAll");
            var directive = compileDirective();
            var scope = directive.isolateScope();
            scope.toggleCheckAll();
            expect($scope.onCheckAll).toHaveBeenCalled();
        });
    });

    describe("toggleChecked", function() {

        it("selects machine", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var machine = makeMachine();
            scope.filteredMachines = [machine];
            scope.toggleChecked(machine);
            expect(machine.$selected).toBe(true);
            expect(scope.table.allViewableChecked).toBe(true);
        });

        it("unselects machine", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var machine = makeMachine();
            scope.filteredMachines = [machine];
            MachinesManager.selectItem(machine.system_id);
            scope.toggleChecked(machine);
            expect(machine.$selected).toBe(false);
            expect(scope.table.allViewableChecked).toBe(false);
        });

        it("calls onCheck", function() {
            $scope.onCheck = jasmine.createSpy("onCheck");
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var machine = makeMachine();
            scope.toggleChecked(machine);
            expect($scope.onCheck).toHaveBeenCalledWith(machine);
        });
    });

    describe("sortTable", function() {

        it("sets predicate", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var predicate = makeName('predicate');
            scope.sortTable(predicate);
            expect(scope.table.predicate).toBe(predicate);
        });

        it("reverses reverse", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            scope.table.reverse = true;
            scope.sortTable(makeName('predicate'));
            expect(scope.table.reverse).toBe(false);
        });
    });

    describe("selectColumnOrSort", function() {

        it("sets column if different", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var column = makeName('column');
            scope.selectColumnOrSort(column);
            expect(scope.table.column).toBe(column);
        });

        it("calls sortTable if column already set", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var column = makeName('column');
            scope.table.column = column;
            spyOn(scope, "sortTable");
            scope.selectColumnOrSort(column);
            expect(scope.sortTable).toHaveBeenCalledWith(column);
        });
    });

    describe("showSpinner", function() {

        it("returns false/true based on status codes", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var STATUSES = [1, 9, 12, 14, 17, 19];
            var i;
            for(i = 0; i < 20; i++) {
                var machine = {
                    status_code: i
                };
                var expected = false;
                if(STATUSES.indexOf(i) > -1) {
                    expected = true;
                }
                expect(scope.showSpinner(machine)).toBe(expected);
            }
        });
    });

    describe("getReleaseTitle", function() {

        it("returns release title from osinfo", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            scope.osinfo = {
                releases: [
                    ['ubuntu/xenial', 'Ubuntu Xenial']
                ]
            };
            expect(scope.getReleaseTitle('ubuntu/xenial')).toBe(
                'Ubuntu Xenial');
        });

        it("returns release name when not in osinfo", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            scope.osinfo = {
                releases: []
            };
            expect(scope.getReleaseTitle('ubuntu/xenial')).toBe(
                'ubuntu/xenial');
        });

        it("returns release name when osinfo.releases undefined", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            scope.osinfo = {
            };
            expect(scope.getReleaseTitle('ubuntu/xenial')).toBe(
                'ubuntu/xenial');
        });
    });

    describe("getStatusText", function() {

        it("returns status text when not deployed or deploying", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var machine = {
                status: makeName("status")
            };

            expect(scope.getStatusText(machine)).toBe(machine.status);
        });

        it("returns status with release title when deploying", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var machine = {
                status: "Deploying",
                osystem: "ubuntu",
                distro_series: "xenial"
            };
            scope.osinfo = {
                releases: [
                    ['ubuntu/xenial', 'Ubuntu Xenial']
                ]
            };
            expect(scope.getStatusText(machine)).toBe(
                'Deploying Ubuntu Xenial');
        });

        it("returns release title when deployed", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var machine = {
                status: "Deployed",
                osystem: "ubuntu",
                distro_series: "xenial"
            };
            scope.osinfo = {
                releases: [
                    ['ubuntu/xenial', 'Ubuntu Xenial']
                ]
            };
            expect(scope.getStatusText(machine)).toBe(
                'Ubuntu Xenial');
        });

        it("returns release title without codename when deployed", function() {
            var directive = compileDirective();
            var scope = directive.isolateScope();
            var machine = {
                status: "Deployed",
                osystem: "ubuntu",
                distro_series: "xenial"
            };
            scope.osinfo = {
                releases: [
                    ['ubuntu/xenial', 'Ubuntu 16.04 LTS "Xenial Xerus"']
                ]
            };
            expect(scope.getStatusText(machine)).toBe(
                'Ubuntu 16.04 LTS');
        });
    });

    describe("onListingChange", function() {

        it("called when filteredMachines changes", function() {
            $scope.onListingChange = jasmine.createSpy('onListingChange');
            var directive = compileDirective();
            var scope = directive.isolateScope();

            var machines = [{}];
            scope.filteredMachines = machines;

            $scope.$digest();
            expect($scope.onListingChange).toHaveBeenCalledWith(machines);
        });
    });
});
