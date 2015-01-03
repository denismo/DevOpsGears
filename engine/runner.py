import heapq
import threading
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.interval import IntervalTrigger

__author__ = 'Denis Mikhalkin'

import json
import os
import subprocess
from boto import sqs
import uuid
from collections import OrderedDict
import yaml
import logging
from pytz import utc

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor

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


class HandlerManager(object):
    handlers = dict()

    def __init__(self, engine):
        self._eventBus = engine.eventBus
        self._resourceManager = engine.resourceManager
        self._eventBus.subscribe(lambda eventName, resource, payload: True, self.handleEvent)

    def registerSubscribe(self, handler, condition):
        self._addHandler("subscribe", {"handler": handler, "condition": DelegatedEventCondition("subscribe", condition)})

    def registerOn(self, handler, condition):
        self._addHandler(condition.eventName, {"handler": handler, "condition": condition})
        self._eventBus.publish("subscribe", self._resourceManager.getMatchingResources(condition), payload={"eventName": condition.eventName})

    def _addHandler(self, event, bundle):
        if event not in self.handlers:
            self.handlers[event] = list(bundle)
        else:
            self.handlers[event].append(bundle)

    def getHandlers(self, eventName, resource):
        if eventName not in self.handlers:
            return list()
        return [bundle.handler for bundle in self.handlers[eventName] if bundle.condition.matchesEvent(eventName, resource)]

    def handleEvent(self, eventName, resource, payload):
        handlers = self.getHandlers(eventName, resource)
        for handler in handlers:
            try:
                handler.handleEvent(eventName, resource, payload)
            except:
                # TODO Log
                pass

class ResourceManager(object):
    _resources = dict()
    # add, update, remove - raise events
    def __init__(self, engine):
        self._engine = engine
        self._eventBus = engine.eventBus
        self.root = Resource("root", "root", None)

    def addResource(self, resource):
        if self.registerResource(resource):
            self.raiseEvent("create", resource)

    def registerResource(self, resource):
        if resource.name not in self._resources:
            self._resources[resource.name] = resource
            return True
        return False

    # condition is resource condition (the "matches" contract)
    def getMatchingResources(self, condition):
        return [resource for resource in self._resources.values() if condition.matches(resource)]

    def raiseEvent(self, eventName, resource):
        self._eventBus.publish(eventName, resource)

class Scheduler(object):

    def __init__(self, engine):
        self.engine = engine
        jobstores = {
            'default': MemoryJobStore()
        }
        executors = {
            'default': ThreadPoolExecutor(1),
        }
        job_defaults = {
            'coalesce': False,
            'max_instances': 1
        }
        self.scheduler = BackgroundScheduler(jobstores=jobstores, executors=executors, job_defaults=job_defaults, timezone=utc)
        self.scheduler.start()

    def schedule(self, callback, periodInSeconds):
        self.scheduler.add_job(callback, IntervalTrigger(seconds=periodInSeconds))

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

class DelegatedEventCondition():
    def __init__(self, eventName=None, resourceCondition=None):
        self._resourceCondition = resourceCondition
        self._eventName = eventName

    def matchesEvent(self, eventName, resource):
        res = self._eventName == eventName
        if not res: return False
        return self.matches(resource)

    def matches(self, resource):
        return self._resourceCondition.matches(resource) if self._resourceCondition is not None else False

class EventCondition(ResourceCondition):
    eventName = ""
    resourceType = None
    resourceName = None
    def __init__(self, eventName=None, resourceType=None, resourceName=None):
        ResourceCondition.__init__(resourceType, resourceName)
        self.eventName = eventName

    def matchesEvent(self, eventName, resource):
        res = self.eventName == eventName
        if not res: return False
        return self.matches(resource)

class Resource(object):
    STATES = {"INVALID": "INVALID", "DEFINED": "DEFINED"}

    type = ""
    name = "" # Unique name of the resource (essentially - ID)
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

    def __init__(self, engine):
        pass

    def publish(self, eventName, resource, payload = None):
        if type(resource) == list:
            resource.map(lambda res: self.publish(eventName, res, payload))
            return
        for (key, obj) in self.listeners:
            if obj.condition(eventName, resource, payload):
                try:
                    obj.callback(eventName, resource, payload)
                except:
                    pass
                    # TODO Logging

    def subscribe(self, condition, callback):
        if condition is None or callback is None:
            return
        subscriptionId = uuid.uuid4()
        self.listeners[subscriptionId] = {"condition": condition, "callback": callback, "id": subscriptionId}
        return subscriptionId

    def unsubscribe(self, subscriptionId):
        del self.listeners[subscriptionId]

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

        self.eventBus.publish("run", self, {"resource": resource, "payload": payload})

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

    # TODO Subscribe's eventName is "subscribe". What was subscribed on should be in payload
    def handleSubscribe(self, eventName, resource, payload):
        if not resource.type == "sqs": return False

        conn = sqs.connect_to_region(resource.desc["region"])

        def poll():
            queue = conn.lookup(resource.desc["queueName"])
            msg = queue.read()
            if msg is not None:
                queue.delete_message(msg)
                self._eventBus.publish(payload["eventName"], self, msg.get_body())

        self._scheduler.schedule(poll, DEFAULT_SUBSCRIBE_PERIOD)


# class GitHandler(object):
#     handlerManager = None
#     """:type HandlerManager"""
#     resourceManager = None
#     """:type ResourceManager"""
#
#     def onEvent(self, eventName, resource, payload):
#         # TODO File path is relative to repository. Who will specify repository configuration?
#         if not eventName == "GitChanged":
#             return
#         gitMessage = json.loads(payload) # See https://developer.github.com/v3/activity/events/types/#pushevent
#         gitMessage["commits"]["added"]  \
#             .filter(lambda fileName: FileHandler.isHandler(fileName))       \
#             .map(lambda fileName: self.handlerManager.registerHandler(FileHandler(fileName)))
#         gitMessage["commits"]["removed"] \
#             .filter(lambda fileName: FileHandler.isHandler(fileName))       \
#             .map(lambda fileName: self.handlerManager.unregisterHandler(FileHandler(fileName)))
#
#         self.resourceManager.suspendEvents()
#         gitMessage["commits"]["added"] \
#             .filter(lambda fileName: not FileHandler.isHandler(fileName)) \
#             .map(lambda fileName: self.resourceManager.addResource(FileResource(fileName))) # Raises events
#
#         gitMessage["commits"]["modified"] \
#             .filter(lambda fileName: not FileHandler.isHandler(fileName)) \
#             .map(lambda fileName: self.resourceManager.updateResource(FileResource(fileName))) # Raises events
#
#         gitMessage["commits"]["removed"] \
#             .filter(lambda fileName: not FileHandler.isHandler(fileName)) \
#             .map(lambda fileName: self.resourceManager.removeResource(FileResource(fileName))) # Raises events
#
#         self.resourceManager.resumeEvents()