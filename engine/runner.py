__author__ = 'Denis Mikhalkin'

import json
import os
import subprocess
from boto import sqs
import uuid
from collections import OrderedDict
import yaml

DEFAULT_SUBSCRIBE_PERIOD = 60 # 1 minute in seconds

class Engine(object):
    resourceManager = None
    """:type ResourceManager"""
    eventBus = None
    """:type EventBus"""
    handlerManager = None
    """:type HandlerManager"""
    scheduler = None
    """:type Scheduler"""

    def __init__(self, config):
        self.eventBus = EventBus(self)
        self.scheduler = Scheduler(self)
        self.handlerManager = HandlerManager(self)
        self.resourceManager = ResourceManager(self)

        self.handlerManager.registerSubscribe(SQSHandler(self), ResourceCondition(resourceType="sqs"))
        self.resourceManager.addResource(Resource("gitqueue", "sqs", self.resourceManager.root, desc=dict(region="ap-southeast-2", queueName="GitChanges"), raisesEvents=["GitChanged"]))
        self.handlerManager.registerOn(GitHandler(), EventCondition(eventName="GitChanged"))

class HandlerManager(object):
    pass

class ResourceManager(object):
    pass

class Scheduler(object):
    pass

class ResourceCondition(object):
    resourceType = None
    resourceName = None
    def __init__(self, resourceType=None, resourceName=None):
        self.resourceType = resourceType
        self.resourceName = resourceName

    def matches(self, resource):
        if self.resourceType is not None:
            if resource is None: return False
            res = self.resourceType == resource.type
            if not res: return False
            if self.resourceName is None:
                return self.resourceName == resource.name

class EventCondition(ResourceCondition):
    eventName = ""
    resourceType = None
    resourceName = None
    def __init__(self, eventName=None, resourceType=None, resourceName=None):
        ResourceCondition.__init__(resourceType, resourceName)
        self.eventName = eventName

    def matchesEvent(self, eventName, resource, payload):
        res = self.eventName == eventName
        if not res: return False
        return self.matches(resource)

class Resource(object):
    STATES = {"INVALID": "INVALID", "DEFINED": "DEFINED"}

    type = ""
    name = ""
    parentResource = None
    parent = ""
    def __init__(self, name, resourceType, parent, desc=None, raisesEvents=list()):
        self.name = name
        self.type = resourceType
        self.parent = parent
        self.desc = desc
        self.raisesEvents = raisesEvents

    def attach(self, resourceManager):
        if self.parent is None: return False
        parent = resourceManager.query(self.parent)
        if parent is not None:
            if resourceManager.attachTo(parent, self):
                self.parentResource = parent
                return True
        return False

class EventBus(object):
    listeners = OrderedDict()

    def publish(self, eventName, resource, payload):
        for (key, obj) in self.listeners:
            if obj.condition.matches(eventName, resource, payload):
                try:
                    obj.callback(eventName, resource, payload)
                except:
                    pass
                    # TODO Logging

    def subscribe(self, condition, callback):
        if condition is None or callback is None:
            return
        id = uuid.uuid4()
        self.listeners[id] = {condition: condition, callback: callback, id: id}
        return id

    def unsubscribe(self, id):
        del self.listeners[id]

# TODO Handle self resource definition (for resources which became folders)
class FileResource(Resource):
    def __init__(self, filename):
        Resource.__init__(self, os.path.splitext(filename)[0], os.path.splitext(filename)[1], os.path.dirname(filename))
        self.filename = filename
        self.readProperties()

    def readProperties(self):
        self.state = Resource.STATES["INVALID"]
        if not os.path.exists(self.filename):
            return

        if os.path.splitext(self.filename)[1] == ".yaml":
            self.desc = yaml.load(self.filename)
            if "resourceType" in self.desc:
                self.type = self.desc["resourceType"]
            self.state = Resource.STATES["DEFINED"]

class FileHandler(object):
    eventBus = None
    """:type EventBus"""

    def __init__(self, fileName):
        self.file = fileName
        self.getEventCondition()

    def getEventCondition(self):
        if hasattr(self, "condition"):
            return self.condition
        if self.file.startswith("on."):
            parts = self.file.split(".")
            self.condition = EventCondition()
            if len(parts) > 2: # contains at least event name
                self.condition.eventName = parts[1]
                if len(parts) > 3: # contains resource type
                    self.condition.resourceType = parts[2]
                    if len(parts) > 4: # contains resource name
                        self.condition.resourceName = parts[3]
            if len(parts) > 1:
                self.type = parts[-1]

    def getEventName(self):
        return self.condition.eventName

    def isRunnable(self):
        opened = file(self.file)
        try:
            firstLine = opened.readline().strip()
            return firstLine is not None and firstLine.startswith("#!")
        finally:
            opened.close()

    @staticmethod
    def isHandler(fileName):
        (head, tail) = fileName.partition(".")
        return head in ["on", "run", "create", "update", "delete"]

    def handleEvent(self, eventName, resource, payload):
        if eventName == self.getEventName():
            self.runHandler(resource, payload)

    def runHandler(self, resource, payload):
        # TODO Log run event
        if self.isRunnable():
            try:
                self.systemExecute(resource, payload)
                # TODO Handle return code
                return
            except OSError:
                # TODO Log error
                pass # Unable to run the script - let's try a run handler

        self.eventBus.publish("run", self, {resource: resource, payload: payload})

    def systemExecute(self, resource, payload):
        return subprocess.call([self.file], env={"RESOURCE": resource, "PAYLOAD": payload})

class SQSHandler(object):
    _scheduler = None
    """:type Scheduler"""
    _eventBus = None
    """:type EventBus"""

    def __init__(self, engine):
        self._eventBus = engine.eventBus
        self._scheduler = engine.scheduler

    # TODO This means that handler manager internally will iterate all resource covered by condition, and execute handler for each of them
    def handleSubscribe(self, eventName, resource):
        if not resource.type == "sqs" or not eventName == "received": return False

        conn = sqs.connect_to_region(resource.desc["region"])

        def poll():
            queue = conn.lookup(resource.desc["queueName"])
            msg = queue.read()
            if msg is not None:
                queue.delete_message(msg)
                self._eventBus.publish(eventName, self, msg.get_body())

        self._scheduler.schedule(poll, DEFAULT_SUBSCRIBE_PERIOD)

class GitHandler(object):
    handlerManager = None
    """:type HandlerManager"""
    resourceManager = None
    """:type ResourceManager"""

    def onEvent(self, eventName, resource, payload):
        # TODO File path is relative to repository. Who will specify repository configuration?
        if not eventName == "GitChanged":
            return
        gitMessage = json.loads(payload) # See https://developer.github.com/v3/activity/events/types/#pushevent
        gitMessage["commits"]["added"]  \
            .filter(lambda fileName: FileHandler.isHandler(fileName))       \
            .map(lambda fileName: self.handlerManager.registerHandler(FileHandler(fileName)))
        gitMessage["commits"]["removed"] \
            .filter(lambda fileName: FileHandler.isHandler(fileName))       \
            .map(lambda fileName: self.handlerManager.unregisterHandler(FileHandler(fileName)))

        self.resourceManager.suspendEvents()
        gitMessage["commits"]["added"] \
            .filter(lambda fileName: not FileHandler.isHandler(fileName)) \
            .map(lambda fileName: self.resourceManager.addResource(FileResource(fileName))) # Raises events

        gitMessage["commits"]["modified"] \
            .filter(lambda fileName: not FileHandler.isHandler(fileName)) \
            .map(lambda fileName: self.resourceManager.updateResource(FileResource(fileName))) # Raises events

        gitMessage["commits"]["removed"] \
            .filter(lambda fileName: not FileHandler.isHandler(fileName)) \
            .map(lambda fileName: self.resourceManager.addResource(FileResource(fileName))) # Raises events

        self.resourceManager.resumeEvents()