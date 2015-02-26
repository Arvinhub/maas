/* Copyright 2015 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Unit tests for Manager.
 */

describe("Manager", function() {

    // Load the MAAS module.
    beforeEach(module("MAAS"));

    // Load the Manager and RegionConnection factory.
    var NodesManager, RegionConnection, webSocket;
    beforeEach(inject(function($injector) {
        var Manager = $injector.get("Manager");
        RegionConnection = $injector.get("RegionConnection");

        // Create a fake node manager
        function FakeNodesManager() {
            Manager.call(this);
            this._pk = "system_id";
            this._handler = "node";
            this._metadataAttributes = [
                "status",
                "owner"
            ];

            // Listen for notify events for the node object.
            var self = this;
            RegionConnection.registerNotifier("node", function(action, data) {
                self.onNotify(action, data);
            });
        }
        FakeNodesManager.prototype = new Manager();
        NodesManager = new FakeNodesManager();

        // Mock buildSocket so an actual connection is not made.
        webSocket = new MockWebSocket();
        spyOn(RegionConnection, "buildSocket").and.returnValue(webSocket);
    }));

    // Open the connection to the region before each test.
    beforeEach(function(done) {
        RegionConnection.registerHandler("open", function() {
            done();
        });
        RegionConnection.connect("");
    });

    // Copy node and remove $selected field.
    function stripSelected(node) {
        node = angular.copy(node);
        delete node.$selected;
        return node;
    }

    // Copy all nodes and remove the $selected field.
    function stripSelectedNodes(nodes) {
        nodes = angular.copy(nodes);
        angular.forEach(nodes, function(node) {
            delete node.$selected;
        });
        return nodes;
    }

    // Add $selected field to node with value.
    function addSelected(node, selected) {
        node.$selected = selected;
        return node;
    }

    // Add $selected field to all nodes with value.
    function addSelectedOnNodes(nodes, selected) {
        angular.forEach(nodes, function(node) {
            node.$selected = selected;
        });
        return nodes;
    }

    // Make a random node.
    function makeNode(selected) {
        var node = {
            system_id: makeName("system_id"),
            name: makeName("name"),
            status: makeName("status"),
            owner: makeName("owner")
        };
        if(angular.isDefined(selected)) {
            node.$selected = selected;
        }
        return node;
    }

    // Make a list of nodes.
    function makeNodes(count, selected) {
        var i, nodes = [];
        for(i = 0; i < count; i++) {
            nodes.push(makeNode(selected));
        }
        return nodes;
    }

    describe("getItems", function() {

        it("returns items array", function() {
            var array = [ makeNode() ];
            NodesManager._items = array;
            expect(NodesManager.getItems()).toBe(array);
        });
    });

    describe("loadItems", function() {

        it("calls reloadItems if the items are already loaded", function() {
            NodesManager._loaded = true;
            spyOn(NodesManager, "reloadItems");
            NodesManager.loadItems();
            expect(NodesManager.reloadItems).toHaveBeenCalled();
        });

        it("calls node.list", function(done) {
            webSocket.returnData.push(makeFakeResponse([makeNode()]));
            NodesManager.loadItems().then(function() {
                var sentObject = angular.fromJson(webSocket.sentData[0]);
                expect(sentObject.method).toBe("node.list");
                done();
            });
        });

        it("loads items list without replacing it", function(done) {
            var fakeNode = makeNode();
            var nodes = NodesManager.getItems();
            webSocket.returnData.push(makeFakeResponse([fakeNode]));
            NodesManager.loadItems().then(function(nodes) {
                expect(nodes).toEqual([addSelected(fakeNode, false)]);
                expect(nodes).toBe(nodes);
                done();
            });
        });

        it("batch calls in groups of 50", function(done) {
            var i, fakeNodes = [];
            for(i = 0; i < 3; i++) {
                var groupOfNodes = makeNodes(50);
                fakeNodes.push.apply(fakeNodes, groupOfNodes);
                webSocket.returnData.push(makeFakeResponse(groupOfNodes));
            }
            // A total of 4 calls should be completed, with the last one
            // being an empty list of nodes.
            webSocket.returnData.push(makeFakeResponse([]));
            NodesManager.loadItems().then(function(nodes) {
                expect(nodes).toEqual(addSelectedOnNodes(fakeNodes, false));
                expect(webSocket.sentData.length).toBe(4);
                expect(webSocket.receivedData.length).toBe(4);
                expect(
                    angular.fromJson(
                        webSocket.receivedData[3]).result).toEqual([]);
                done();
            });
        });

        it("batch calls with the last system_id", function(done) {
            var fakeNodes = makeNodes(50);
            var system_id = fakeNodes[fakeNodes.length-1].system_id;
            webSocket.returnData.push(makeFakeResponse(fakeNodes));
            // A total of 2 calls should be completed, with the last one
            // being an empty list of nodes.
            webSocket.returnData.push(makeFakeResponse([]));
            NodesManager.loadItems().then(function(nodes) {
                // Expect first message to not have a start.
                first_msg = angular.fromJson(webSocket.sentData[0]);
                expect(first_msg.params.start).toBeUndefined();

                // Expect the second message to have the last system_id.
                second_msg = angular.fromJson(webSocket.sentData[1]);
                expect(second_msg.params.start).toEqual(system_id);
                done();
            });
        });

        it("sets loaded true when complete", function(done) {
            webSocket.returnData.push(makeFakeResponse([makeNode()]));
            NodesManager.loadItems().then(function() {
                expect(NodesManager._loaded).toBe(true);
                done();
            });
        });

        it("sets isLoading to true while loading", function(done) {
            NodesManager._isLoading = false;
            webSocket.returnData.push(makeFakeResponse("error", true));
            NodesManager.loadItems().then(null, function() {
                expect(NodesManager._isLoading).toBe(true);
                done();
            });
        });

        it("sets isLoading to false after loading", function(done) {
            NodesManager._isLoading = true;
            webSocket.returnData.push(makeFakeResponse([makeNode()]));
            NodesManager.loadItems().then(function() {
                expect(NodesManager._isLoading).toBe(false);
                done();
            });
        });

        it("calls processActions after loading", function(done) {
            spyOn(NodesManager, "processActions");
            webSocket.returnData.push(makeFakeResponse([makeNode()]));
            NodesManager.loadItems().then(function() {
                expect(NodesManager.processActions).toHaveBeenCalled();
                done();
            });
        });

        it("calls defer error handler on error", function(done) {
            var errorMsg = "Unable to load the nodes.";
            webSocket.returnData.push(makeFakeResponse(errorMsg, true));
            NodesManager.loadItems().then(null, function(error) {
                expect(error).toBe(errorMsg);
                done();
            });
        });

        it("doesn't set loaded to true on error", function(done) {
            var errorMsg = "Unable to load the nodes.";
            webSocket.returnData.push(makeFakeResponse(errorMsg, true));
            NodesManager.loadItems().then(null, function() {
                expect(NodesManager._loaded).toBe(false);
                done();
            });
        });

        it("returns nodes list in defer", function(done) {
            webSocket.returnData.push(makeFakeResponse([makeNode()]));
            NodesManager.loadItems().then(function(nodes) {
                expect(nodes).toBe(NodesManager.getItems());
                done();
            });
        });

        it("updates the node status", function(done) {
            var node = makeNode();
            webSocket.returnData.push(makeFakeResponse([node]));
            NodesManager.loadItems().then(function(nodes) {
                expect(NodesManager._metadata.status).toEqual([{
                    name: node.status,
                    count: 1
                }]);
                done();
            });
        });

        it("updates the node owner", function(done) {
            var node = makeNode();
            webSocket.returnData.push(makeFakeResponse([node]));
            NodesManager.loadItems().then(function(nodes) {
                expect(NodesManager._metadata.owner).toEqual([{
                    name: node.owner,
                    count: 1
                }]);
                done();
            });
        });
    });

    describe("reloadItems", function() {

        beforeEach(function() {
            NodesManager._loaded = true;
        });

        it("calls loadItems if the nodes are not loaded", function() {
            NodesManager._loaded = false;
            spyOn(NodesManager, "loadItems");
            NodesManager.reloadItems();
            expect(NodesManager.loadItems).toHaveBeenCalled();
        });

        it("sets isLoading to true while reloading", function(done) {
            NodesManager._isLoading = false;
            webSocket.returnData.push(makeFakeResponse("error", true));
            NodesManager.reloadItems().then(null, function() {
                expect(NodesManager._isLoading).toBe(true);
                done();
            });
        });

        it("sets isLoading to false after reloading", function(done) {
            NodesManager._isLoading = true;
            webSocket.returnData.push(makeFakeResponse([makeNode()]));
            NodesManager.reloadItems().then(function() {
                expect(NodesManager._isLoading).toBe(false);
                done();
            });
        });

        it("calls processActions after loading", function(done) {
            spyOn(NodesManager, "processActions");
            webSocket.returnData.push(makeFakeResponse([makeNode()]));
            NodesManager.reloadItems().then(function() {
                expect(NodesManager.processActions).toHaveBeenCalled();
                done();
            });
        });

        it("calls defer error handler on error", function(done) {
            var errorMsg = "Unable to reload the nodes.";
            webSocket.returnData.push(makeFakeResponse(errorMsg, true));
            NodesManager.reloadItems().then(null, function(error) {
                expect(error).toBe(errorMsg);
                done();
            });
        });

        it("returns nodes list in defer", function(done) {
            webSocket.returnData.push(makeFakeResponse([makeNode()]));
            NodesManager.reloadItems().then(function(nodes) {
                expect(nodes).toBe(NodesManager.getItems());
                done();
            });
        });

        it("adds new nodes to items list", function(done) {
            var currentNodes = [makeNode(), makeNode()];
            var newNodes = [makeNode(), makeNode()];
            var allNodes = currentNodes.concat(newNodes);
            NodesManager._items = currentNodes;
            webSocket.returnData.push(makeFakeResponse(allNodes));
            NodesManager.reloadItems().then(function(nodes) {
                expect(nodes).toEqual(allNodes);
                done();
            });
        });

        it("removes missing nodes from items list", function(done) {
            var currentNodes = [makeNode(), makeNode(), makeNode()];
            var removedNodes = angular.copy(currentNodes);
            removedNodes.splice(1, 1);
            NodesManager._items = currentNodes;
            webSocket.returnData.push(makeFakeResponse(removedNodes));
            NodesManager.reloadItems().then(function(nodes) {
                expect(nodes).toEqual(removedNodes);
                done();
            });
        });

        it("removes missing nodes from selected items list", function(done) {
            var currentNodes = [makeNode(), makeNode(), makeNode()];
            var removedNodes = angular.copy(currentNodes);
            removedNodes.splice(1, 1);
            NodesManager._items = currentNodes;
            NodesManager._selectedItems = [currentNodes[0], currentNodes[1]];
            webSocket.returnData.push(makeFakeResponse(removedNodes));
            NodesManager.reloadItems().then(function(nodes) {
                expect(NodesManager._selectedItems).toEqual([currentNodes[0]]);
                done();
            });
        });

        it("updates nodes in items list", function(done) {
            var currentNodes = [makeNode(), makeNode()];
            var updatedNodes = angular.copy(currentNodes);
            updatedNodes[0].name = makeName("name");
            updatedNodes[1].name = makeName("name");
            NodesManager._items = currentNodes;
            webSocket.returnData.push(makeFakeResponse(updatedNodes));
            NodesManager.reloadItems().then(function(nodes) {
                expect(nodes).toEqual(updatedNodes);
                done();
            });
        });

        it("updates nodes in selected items list", function(done) {
            var currentNodes = [makeNode(true), makeNode(true)];
            var updatedNodes = stripSelectedNodes(currentNodes);
            updatedNodes[0].name = makeName("name");
            updatedNodes[1].name = makeName("name");
            NodesManager._items = currentNodes;
            NodesManager._selectedItems = [currentNodes[0], currentNodes[1]];
            webSocket.returnData.push(makeFakeResponse(updatedNodes));
            NodesManager.reloadItems().then(function(nodes) {
                expect(NodesManager._selectedItems).toEqual(
                    addSelectedOnNodes(updatedNodes, true));
                done();
            });
        });
    });

    describe("enableAutoReload", function() {

        it("does nothing if already enabled", function() {
            spyOn(RegionConnection, "registerHandler");
            NodesManager._autoReload = true;
            NodesManager.enableAutoReload();
            expect(RegionConnection.registerHandler).not.toHaveBeenCalled();
        });

        it("adds handler and sets autoReload to true", function() {
            spyOn(RegionConnection, "registerHandler");
            NodesManager.enableAutoReload();
            expect(RegionConnection.registerHandler).toHaveBeenCalled();
            expect(NodesManager._autoReload).toBe(true);
        });
    });

    describe("disableAutoReload", function() {

        it("does nothing if already disabled", function() {
            spyOn(RegionConnection, "unregisterHandler");
            NodesManager._autoReload = false;
            NodesManager.disableAutoReload();
            expect(RegionConnection.unregisterHandler).not.toHaveBeenCalled();
        });

        it("removes handler and sets autoReload to false", function() {
            spyOn(RegionConnection, "unregisterHandler");
            NodesManager._autoReload = true;
            NodesManager.disableAutoReload();
            expect(RegionConnection.unregisterHandler).toHaveBeenCalled();
            expect(NodesManager._autoReload).toBe(false);
        });
    });

    describe("getItem", function() {

        it("calls node.get", function(done) {
            var fakeNode = makeNode();
            webSocket.returnData.push(makeFakeResponse(fakeNode));
            NodesManager.getItem(fakeNode.system_id).then(function() {
                var sentObject = angular.fromJson(webSocket.sentData[0]);
                expect(sentObject.method).toBe("node.get");
                done();
            });
        });

        it("calls node.get with node system_id", function(done) {
            var fakeNode = makeNode();
            webSocket.returnData.push(makeFakeResponse(fakeNode));
            NodesManager.getItem(fakeNode.system_id).then(function() {
                var sentObject = angular.fromJson(webSocket.sentData[0]);
                expect(sentObject.params.system_id).toBe(fakeNode.system_id);
                done();
            });
        });

        it("updates node in items and selectedItems list", function(done) {
            var fakeNode = makeNode();
            var updatedNode = angular.copy(fakeNode);
            updatedNode.name = makeName("name");

            NodesManager._items.push(fakeNode);
            NodesManager._selectedItems.push(fakeNode);
            webSocket.returnData.push(makeFakeResponse(updatedNode));
            NodesManager.getItem(fakeNode.system_id).then(function() {
                expect(NodesManager._items[0].name).toBe(updatedNode.name);
                expect(NodesManager._selectedItems[0].name).toBe(
                    updatedNode.name);
                done();
            });
        });

        it("calls defer error handler on error", function(done) {
            var errorMsg = "No node with the given system_id.";
            webSocket.returnData.push(makeFakeResponse(errorMsg, true));
            NodesManager.getItem(makeName("system_id")).then(
                null, function(error) {
                    expect(error).toBe(errorMsg);
                    done();
                });
        });
    });

    describe("updateItem", function() {

        it("calls node.update", function(done) {
            var fakeNode = makeNode();
            webSocket.returnData.push(makeFakeResponse(fakeNode));
            NodesManager.updateItem(fakeNode).then(function() {
                var sentObject = angular.fromJson(webSocket.sentData[0]);
                expect(sentObject.method).toBe("node.update");
                done();
            });
        });

        it("calls node.update with node", function(done) {
            var fakeNode = makeNode();
            webSocket.returnData.push(makeFakeResponse(fakeNode));
            NodesManager.updateItem(fakeNode).then(function() {
                var sentObject = angular.fromJson(webSocket.sentData[0]);
                expect(sentObject.params).toEqual(fakeNode);
                done();
            });
        });

        it("updates node in items and selectedItems list", function(done) {
            var fakeNode = makeNode();
            var updatedNode = angular.copy(fakeNode);
            updatedNode.name = makeName("name");

            NodesManager._items.push(fakeNode);
            NodesManager._selectedItems.push(fakeNode);
            webSocket.returnData.push(makeFakeResponse(updatedNode));
            NodesManager.updateItem(updatedNode).then(function() {
                expect(NodesManager._items[0].name).toBe(updatedNode.name);
                expect(NodesManager._selectedItems[0].name).toBe(
                    updatedNode.name);
                done();
            });
        });

        it("calls defer error handler on error", function(done) {
            var errorMsg = "Unable to update node";
            webSocket.returnData.push(makeFakeResponse(errorMsg, true));
            NodesManager.updateItem(makeNode()).then(null, function(error) {
                expect(error).toBe(errorMsg);
                done();
            });
        });
    });

    describe("deleteItem", function() {

        it("calls node.delete", function(done) {
            var fakeNode = makeNode();
            webSocket.returnData.push(makeFakeResponse(null));
            NodesManager.deleteItem(fakeNode).then(function() {
                var sentObject = angular.fromJson(webSocket.sentData[0]);
                expect(sentObject.method).toBe("node.delete");
                done();
            });
        });

        it("calls node.delete with node system_id", function(done) {
            var fakeNode = makeNode();
            webSocket.returnData.push(makeFakeResponse(null));
            NodesManager.deleteItem(fakeNode).then(function() {
                var sentObject = angular.fromJson(webSocket.sentData[0]);
                expect(sentObject.params.system_id).toBe(fakeNode.system_id);
                done();
            });
        });

        it("deletes node in items and selectedItems list", function(done) {
            var fakeNode = makeNode();
            NodesManager._items.push(fakeNode);
            NodesManager._selectedItems.push(fakeNode);
            webSocket.returnData.push(makeFakeResponse(null));
            NodesManager.deleteItem(fakeNode).then(function() {
                expect(NodesManager._items.length).toBe(0);
                expect(NodesManager._selectedItems.length).toBe(0);
                done();
            });
        });
    });

    describe("onNotify", function() {

        it("adds notify to queue", function() {
            var node = makeNode();
            NodesManager._isLoading = true;
            NodesManager.onNotify("create", node);
            expect(NodesManager._actionQueue).toEqual([{
                action: "create",
                data: node
            }]);
        });

        it("skips processActions when isLoading is true",
            function() {
                spyOn(NodesManager, "processActions");
                NodesManager._isLoading = true;
                NodesManager.onNotify("create", makeName("system_id"));
                expect(NodesManager.processActions).not.toHaveBeenCalled();
            });

        it("calls processActions when isLoading is false",
            function() {
                spyOn(NodesManager, "processActions");
                NodesManager._isLoading = false;
                NodesManager.onNotify("create", makeName("system_id"));
                expect(NodesManager.processActions).toHaveBeenCalled();
            });
    });

    describe("processActions", function() {

        it("adds node to items list on create action", function() {
            var fakeNode = makeNode();
            NodesManager._actionQueue.push({
                action: "create",
                data: fakeNode
            });
            NodesManager.processActions();
            expect(NodesManager._items).toEqual(
                [addSelected(fakeNode, false)]);
        });

        it("updates node in items list on update action", function() {
            var fakeNode = makeNode(false);
            var updatedNode = stripSelected(fakeNode);
            updatedNode.name = makeName("name");
            NodesManager._items.push(fakeNode);
            NodesManager._actionQueue.push({
                action: "update",
                data: updatedNode
            });
            NodesManager.processActions();
            expect(NodesManager._items).toEqual(
                [addSelected(updatedNode, false)]);
        });

        it("updates node in selected items on update action", function() {
            var fakeNode = makeNode(true);
            var updatedNode = stripSelected(fakeNode);
            updatedNode.name = makeName("name");
            NodesManager._items.push(fakeNode);
            NodesManager._selectedItems.push(fakeNode);
            NodesManager._actionQueue.push({
                action: "update",
                data: updatedNode
            });
            NodesManager.processActions();
            expect(NodesManager._selectedItems).toEqual(
                [addSelected(updatedNode, true)]);
        });

        it("deletes node in items list on delete action", function() {
            var fakeNode = makeNode();
            NodesManager._items.push(fakeNode);
            NodesManager._actionQueue.push({
                action: "delete",
                data: fakeNode.system_id
            });
            NodesManager.processActions();
            expect(NodesManager._items.length).toBe(0);
        });

        it("deletes node in selected items on delete action", function() {
            var fakeNode = makeNode();
            NodesManager._items.push(fakeNode);
            NodesManager._selectedItems.push(fakeNode);
            NodesManager._actionQueue.push({
                action: "delete",
                data: fakeNode.system_id
            });
            NodesManager.processActions();
            expect(NodesManager._selectedItems.length).toBe(0);
        });

        it("processes multiple actions in one call", function() {
            NodesManager._actionQueue = [
                {
                    action: "delete",
                    data: makeName("system_id")
                },
                {
                    action: "delete",
                    data: makeName("system_id")
                }
            ];
            NodesManager.processActions();
            expect(NodesManager._actionQueue.length).toBe(0);
        });
    });

    describe("getSelectedItems", function() {

        it("returns selected items", function() {
            var nodes = [makeNode()];
            NodesManager._selectedItems = nodes;
            expect(NodesManager.getSelectedItems()).toBe(nodes);
        });
    });

    describe("selectItem", function() {

        it("adds node to selected items", function() {
            var node = makeNode(false);
            NodesManager._items.push(node);
            NodesManager.selectItem(node.system_id);
            expect(NodesManager._selectedItems).toEqual(
                [addSelected(node, true)]);
        });

        it("doesnt add the same node twice", function() {
            var node = makeNode(false);
            NodesManager._items.push(node);
            NodesManager.selectItem(node.system_id);
            NodesManager.selectItem(node.system_id);
            expect(NodesManager._selectedItems).toEqual(
                [addSelected(node, true)]);
        });
    });

    describe("unselectItem", function() {

        var node;
        beforeEach(function() {
            node = makeNode(false);
            NodesManager._items.push(node);
            NodesManager.selectItem(node.system_id);
        });

        it("removes node from selected items", function() {
            NodesManager.unselectItem(node.system_id);
            expect(NodesManager._selectedItems).toEqual([]);
            expect(node.$selected).toBe(false);
        });

        it("doesnt error on unselect twice", function() {
            NodesManager.unselectItem(node.system_id);
            NodesManager.unselectItem(node.system_id);
            expect(NodesManager._selectedItems).toEqual([]);
            expect(node.$selected).toBe(false);
        });
    });

    describe("isSelected", function() {

        var node;
        beforeEach(function() {
            node = makeNode(false);
            NodesManager._items.push(node);
        });

        it("returns true when selected", function() {
            NodesManager.selectItem(node.system_id);
            expect(NodesManager.isSelected(node.system_id)).toBe(true);
        });

        it("returns false when not selected", function() {
            NodesManager.selectItem(node.system_id);
            NodesManager.unselectItem(node.system_id);
            expect(NodesManager.isSelected(node.system_id)).toBe(false);
        });
    });

    var scenarios = ['status', 'owner'];

    angular.forEach(scenarios, function(scenario) {

        describe("_updateMetadata:" + scenario, function() {

            it("adds value if missing", function() {
                var node = makeNode();
                NodesManager._updateMetadata(node, "create");
                expect(NodesManager._metadata[scenario]).toEqual([{
                    name: node[scenario],
                    count: 1
                }]);
            });

            it("increments count for value", function() {
                var node = makeNode();
                NodesManager._updateMetadata(node, "create");
                expect(NodesManager._metadata[scenario]).toEqual([{
                    name: node[scenario],
                    count: 1
                }]);
                NodesManager._updateMetadata(node, "create");
                expect(NodesManager._metadata[scenario]).toEqual([{
                    name: node[scenario],
                    count: 2
                }]);
                NodesManager._updateMetadata(node, "create");
                expect(NodesManager._metadata[scenario]).toEqual([{
                    name: node[scenario],
                    count: 3
                }]);
            });

            it("decrements count for value", function() {
                var node = makeNode();
                NodesManager._updateMetadata(node, "create");
                NodesManager._updateMetadata(node, "create");
                NodesManager._updateMetadata(node, "delete");
                expect(NodesManager._metadata[scenario]).toEqual([{
                    name: node[scenario],
                    count: 1
                }]);
            });

            it("removes value when count is 0", function() {
                var node = makeNode();
                NodesManager._updateMetadata(node, "create");
                NodesManager._updateMetadata(node, "delete");
                expect(NodesManager._metadata[scenario]).toEqual([]);
            });

            it("update doesn't add value if missing", function() {
                var node = makeNode();
                NodesManager._updateMetadata(node, "update");
                expect(NodesManager._metadata[scenario]).toEqual([]);
            });

            it("update decrements value then increments new value", function() {
                var node = makeNode();
                NodesManager._updateMetadata(node, "create");
                NodesManager._updateMetadata(node, "create");
                NodesManager._items.push(node);
                var updatedNode = angular.copy(node);
                updatedNode[scenario] = makeName(scenario);
                NodesManager._updateMetadata(updatedNode, "update");
                expect(NodesManager._metadata[scenario]).toEqual([
                    {
                        name: node[scenario],
                        count: 1
                    },
                    {
                        name: updatedNode[scenario],
                        count: 1
                    }]);
            });

            it("update removes old value then adds new value", function() {
                var node = makeNode();
                NodesManager._updateMetadata(node, "create");
                NodesManager._items.push(node);
                var updatedNode = angular.copy(node);
                updatedNode[scenario] = makeName(scenario);
                NodesManager._updateMetadata(updatedNode, "update");
                expect(NodesManager._metadata[scenario]).toEqual([{
                    name: updatedNode[scenario],
                    count: 1
                }]);
            });

            it("ignores empty values", function() {
                var node = makeNode();
                node.owner = "";
                node.status = "";
                NodesManager._updateMetadata(node, "create");
                expect(NodesManager._metadata[scenario]).toEqual([]);
            });

            it("update handlers empty old values", function() {
                var node = makeNode();
                node[scenario] = "";
                NodesManager._updateMetadata(node, "create");
                NodesManager._items.push(node);
                var updatedNode = angular.copy(node);
                updatedNode[scenario] = makeName(scenario);
                NodesManager._updateMetadata(updatedNode, "update");
                expect(NodesManager._metadata[scenario]).toEqual([{
                    name: updatedNode[scenario],
                    count: 1
                }]);
            });

            it("update handlers empty new values", function() {
                var node = makeNode();
                NodesManager._updateMetadata(node, "create");
                NodesManager._items.push(node);
                var updatedNode = angular.copy(node);
                updatedNode[scenario] = "";
                NodesManager._updateMetadata(updatedNode, "update");
                expect(NodesManager._metadata[scenario]).toEqual([]);
            });
        });

    });
});