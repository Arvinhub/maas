/* Copyright 2016 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Unit tests for DomainsListController.
 */

describe("DomainsListController", function() {

    // Load the MAAS module.
    beforeEach(module("MAAS"));

    // Grab the needed angular pieces.
    var $controller, $rootScope, $scope, $q, $routeParams;
    beforeEach(inject(function($injector) {
        $controller = $injector.get("$controller");
        $rootScope = $injector.get("$rootScope");
        $scope = $rootScope.$new();
        $q = $injector.get("$q");
        $routeParams = {};
    }));

    // Load the managers and services.
    var DomainsManager, UsersManager;
    var ManagerHelperService, RegionConnection;
    beforeEach(inject(function($injector) {
        DomainsManager = $injector.get("DomainsManager");
        UsersManager = $injector.get("UsersManager");
        ManagerHelperService = $injector.get("ManagerHelperService");
    }));

    // Makes the DomainsListController
    function makeController(loadManagerDefer, defaultConnectDefer) {
        var loadManagers = spyOn(ManagerHelperService, "loadManagers");
        if(angular.isObject(loadManagerDefer)) {
            loadManagers.and.returnValue(loadManagerDefer.promise);
        } else {
            loadManagers.and.returnValue($q.defer().promise);
        }

        // Create the controller.
        var controller = $controller("DomainsListController", {
            $scope: $scope,
            $rootScope: $rootScope,
            $routeParams: $routeParams,
            DomainsManager: DomainsManager,
            ManagerHelperService: ManagerHelperService
        });

        return controller;
    }

    it("sets title and page on $rootScope", function() {
        var controller = makeController();
        expect($rootScope.title).toBe("DNS");
        expect($rootScope.page).toBe("domains");
    });

    it("sets initial values on $scope", function() {
        // tab-independent variables.
        var controller = makeController();
        expect($scope.domains).toBe(DomainsManager.getItems());
        expect($scope.loading).toBe(true);
    });

    it("calls loadManagers with [DomainsManager, UsersManager]",
        function() {
            var controller = makeController();
            expect(ManagerHelperService.loadManagers).toHaveBeenCalledWith(
                $scope, [DomainsManager, UsersManager]);
        });

    it("sets loading to false when loadManagers resolves", function() {
        var defer = $q.defer();
        var controller = makeController(defer);
        defer.resolve();
        $rootScope.$digest();
        expect($scope.loading).toBe(false);
    });

    describe("addDomain", function() {

        it("calls show in addDomainScope", function() {
            var controller = makeController();
            $scope.addDomainScope = {
                show: jasmine.createSpy("show")
            };
            $scope.addDomain();
            expect($scope.addDomainScope.show).toHaveBeenCalled();
        });
    });

    describe("cancelAddDomain", function() {

        it("calls cancel in addDomainScope", function() {
            var controller = makeController();
            $scope.addDomainScope = {
                cancel: jasmine.createSpy("cancel")
            };
            $scope.cancelAddDomain();
            expect($scope.addDomainScope.cancel).toHaveBeenCalled();
        });
    });

    setupController = function(domains) {
        var defer = $q.defer();
        var controller = makeController(defer);
        $scope.domains = domains;
        DomainsManager._items = domains;
        defer.resolve();
        $rootScope.$digest();
        return controller;
    };

    testUpdates = function(controller, domains, expectedDomainsData) {
        $scope.domains = domains;
        DomainsManager._items = domains;
        $rootScope.$digest();
        expect($scope.data).toEqual(expectedDomainsData);
    };
});
