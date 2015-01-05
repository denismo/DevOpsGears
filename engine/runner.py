__author__ = 'Denis Mikhalkin'

import os
import subprocess
import uuid
from collections import OrderedDict

from boto import sqs
import yaml
from pytz import utc
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
import logging

DEFAULT_SUBSCRIBE_PERIOD = 15 # 1 minute in seconds

class Engine(object):
    LOG = logging.getLogger("gears.Engine")

    resourceManager = None
    """:type ResourceManager"""
    eventBus = None
    """:type EventBus"""
    handlerManager = None
    """:type HandlerManager"""
    scheduler = None
    """:type Scheduler"""

    def __init__(self, config):
        self.LOG.info("Starting engine")
        self.config = config
        self.eventBus = EventBus(self)
        self.scheduler = Scheduler(self)
        self.resourceManager = ResourceManager(self)
        self.handlerManager = HandlerManager(self)
        self.LOG.info("Started")

class HandlerManager(object):
    LOG = logging.getLogger("gears.HandlerManager")
    handlers = dict()

    def __init__(self, engine):
        self._eventBus = engine.eventBus
        self._resourceManager = engine.resourceManager
        self._eventBus.subscribe(lambda eventName, resource, payload: True, self.handleEvent)
        self.LOG.info("Created")

    def registerSubscribe(self, handler, condition):
        self.LOG.info("registerSubscribe: " + str(condition))
        self._addHandler("subscribe", {"handler": handler, "condition": DelegatedEventCondition("subscribe", condition)})

    def registerOn(self, handler, condition):
        self.LOG.info("registerOn: " + str(condition))
        self._addHandler(condition.eventName, {"handler": handler, "condition": condition})
        self._eventBus.publish("subscribe", self._resourceManager.getMatchingResources(condition), payload={"eventName": condition.eventName})

    def _addHandler(self, event, bundle):
        if event not in self.handlers:
            self.handlers[event] = [bundle]
        else:
            self.handlers[event].append(bundle)

    def getHandlers(self, eventName, resource):
        if eventName not in self.handlers:
            return list()
        return [bundle["handler"] for bundle in self.handlers[eventName] if bundle["condition"].matchesEvent(eventName, resource)]

    def handleEvent(self, eventName, resource, payload):
        self.LOG.info("handleEvent(eventName=%s, resource=%s, payload=%s)" % (eventName, resource, payload))
        handlers = self.getHandlers(eventName, resource)
        if len(handlers) == 0:
            self.LOG.info("-> No handlers for this event")
            return
        for handler in handlers:
            try:
                handler.handleEvent(eventName, resource, payload)
            except:
                self.LOG.exception("-> error invoking handler")
                pass

class ResourceManager(object):
    LOG = logging.getLogger("gears.ResourceManager")
    _resources = dict()
    # add, update, remove - raise events
    def __init__(self, engine):
        self._engine = engine
        self._eventBus = engine.eventBus
        self.root = Resource("root", "root", None)
        self.LOG.info("Created")

    def addResource(self, resource):
        self.LOG.info("addResource(%s)" % resource)
        if self.registerResource(resource):
            self.raiseEvent("register", resource)

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
    LOG = logging.getLogger("gears.Scheduler")
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

    def schedule(self, name, callback, periodInSeconds):
        self.LOG.info("schedule(%s,%s)" % (name, str(periodInSeconds)))
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
            if self.resourceName is not None:
                return self.resourceName == resource.name
            return True

    def __str__(self):
        return "ResourceCondition(type=%s, name=%s)" % (self.resourceType, self.resourceName)

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

    def __str__(self):
        return "DelegatedEventCondition(event=%s, type=%s, name=%s)" % (self._eventName, self._resourceCondition.resourceType, self._resourceCondition.resourceName)

class EventCondition(ResourceCondition):
    eventName = ""
    resourceType = None
    resourceName = None
    def __init__(self, eventName=None, resourceType=None, resourceName=None):
        ResourceCondition.__init__(self, resourceType, resourceName)
        self.eventName = eventName

    def matchesEvent(self, eventName, resource):
        res = self.eventName == eventName
        if not res: return False
        return self.matches(resource)

    def __str__(self):
        return "EventCondition(event=%s, type=%s, name=%s)" % (self.eventName, self.resourceType, self.resourceName)

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

    def __str__(self):
        return "Resource(type=%s, name=%s, parent=%s)" % (self.type, self.name, self.parent)

class EventBus(object):
    LOG = logging.getLogger("gears.EventBus")
    listeners = OrderedDict()

    def __init__(self, engine):
        self.LOG.info("Created")
        pass

    def publish(self, eventName, resource, payload = None):
        self.LOG.info("publish(event=%s, resource=%s, payload=%s)" % (eventName, resource, payload))
        if type(resource) == list:
            for res in resource:
                self.publish(eventName, res, payload)
            return
        for obj in self.listeners.values():
            if obj["condition"](eventName, resource, payload):
                try:
                    obj["callback"](eventName, resource, payload)
                except:
                    self.LOG.exception("-> error calling callback")
                    pass

    def subscribe(self, condition, callback):
        self.LOG.info("subscribe(condition=%s)" % str(condition))
        if condition is None or callback is None:
            return
        subscriptionId = uuid.uuid4()
        self.listeners[subscriptionId] = {"condition": condition, "callback": callback, "id": subscriptionId}
        return subscriptionId

    def unsubscribe(self, subscriptionId):
        del self.listeners[subscriptionId]

class Handler(object):
    LOG = logging.getLogger("gears.handlers.Handler")
    def handleEvent(self, eventName, resource, payload):
        if eventName == "register":
            return self.handleRegister(resource, payload)
        elif eventName == "subscribe":
            return self.handleSubscribe(resource, payload)
        else: self.LOG.error("Unhandled event %s on %s with %s" % (eventName, resource, payload))

    def handleRegister(self, resource, payload):
        pass
    def handleSubscribe(self, resource, payload):
        self.LOG.error("Unhandled 'subscribe' on %s with %s" % (resource, payload))
        pass




