import datetime
from engine.async import ResultObj

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

def get_class( kls ):
    parts = kls.split('.')
    module = ".".join(parts[:-1])
    m = __import__( module )
    for comp in parts[1:]:
        m = getattr(m, comp)
    return m

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
        if "repositoryPath" in config:
            self.repository = Repository(self, config["repositoryPath"])
            self.repository.scan()

        self.LOG.info("Started")

class HandlerManager(object):
    LOG = logging.getLogger("gears.HandlerManager")
    handlers = dict()

    def __init__(self, engine):
        self._engine = engine
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
        self._eventBus.publish("subscribe", condition, payload={"eventName": condition.eventName})

    def registerHandler(self, handler):
        if handler is None: return
        if type(handler) == str:
            handler = self.createHandler(handler)
        eventNames = handler.getEventNames()
        for eventName in eventNames:
            condition = handler.getEventCondition(eventName)
            if eventName == "subscribe":
                self.registerSubscribe(handler, condition)
            # TODO Other event names
            elif not Handler.isActionHandler(eventName):
                self.registerOn(handler, condition)

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

    def createHandler(self, handlerClass):
        return get_class(handlerClass)(self._engine)

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
            self.raiseEvent("register", resource) \
                .success(resource.toState("REGISTERED")) \
                .failure(resource.toState("FAILED"))
        else:
            self.LOG.warn("Unable to register resource: %s" % resource)

    def registerResource(self, resource):
        if resource.name not in self._resources:
            self._resources[resource.name] = resource
            if hasattr(resource, "behavior"):
                if type(resource.behavior) is list:
                    for behavior in resource.behavior:
                        self._engine.handlerManager.registerHandler(behavior)
                else:
                    self._engine.handlerManager.registerHandler(resource.behavior)
            return True
        return False

    # condition is resource condition (the "matches" contract)
    def getMatchingResources(self, condition):
        return [resource for resource in self._resources.values() if condition.matches(resource)]

    def raiseEvent(self, eventName, resource):
        return self._eventBus.publish(eventName, resource)

    def dump(self):
        print "Resources:"
        for resource in self._resources.values():
            print resource

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

class Condition(object):
    def matches(self, obj):
        return False

class ResourceCondition(Condition):
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

class DelegatedEventCondition(Condition):
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
    STATES = {"INVALID": "INVALID", "ADDED": "ADDED", "REGISTERED":"REGISTERED", "PENDING_ACTIVATION":"PENDING_ACTIVATION", "ACTIVATED":"ACTIVATED", "FAILED":"FAILED"}

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
        self.state = self.STATES["INVALID"]

    def attach(self, resourceManager):
        if self.parent is None: return False
        parent = resourceManager.query(self.parent)
        if parent is not None:
            if resourceManager.attachTo(parent, self):
                self.parentResource = parent
                return True
        return False

    def toState(self, newState):
        def transition():
            self.state = newState
        return transition

    def __str__(self):
        return "Resource(type=%s, name=%s, parent=%s, state=%s)" % (self.type, self.name, self.parent, self.state)

class EventBus(object):
    LOG = logging.getLogger("gears.EventBus")
    _listeners = OrderedDict()
    _eventsSuspended = False
    _recordedEvents = list()

    def __init__(self, engine):
        self._engine = engine
        self.LOG.info("Created")
        pass

    def publish(self, eventName, resource, payload = None, resultObject = None):
        if self._eventsSuspended:
            self.LOG.info("publish suspended(event=%s, resource=%s, payload=%s)" % (eventName, resource, payload))
            delayed = ResultObj()
            self._recordedEvents.append((eventName, resource, payload, delayed))
            return delayed

        self.LOG.info("publish(event=%s, resource=%s, payload=%s)" % (eventName, resource, payload))
        if issubclass(type(resource), Condition):
            resource = self._engine.resourceManager.getMatchingResources(resource)

        if type(resource) == list:
            chained = None
            for res in resource:
                result = self.publish(eventName, res, payload)
                if chained is not None:
                    chained = chained.append(result)
                else:
                    chained = result
            return resultObject.append(chained).trigger() if resultObject is not None else chained.trigger()

        result = True
        for obj in self._listeners.values():
            if obj["condition"](eventName, resource, payload):
                try:
                    result = result and obj["callback"](eventName, resource, payload)
                except:
                    self.LOG.exception("-> error calling callback")
                    pass
        if resultObject is not None:
            return resultObject.trigger(result)
        else:
            return ResultObj(result)

    def subscribe(self, condition, callback):
        self.LOG.info("subscribe(condition=%s)" % str(condition))
        if condition is None or callback is None:
            return
        subscriptionId = uuid.uuid4()
        self._listeners[subscriptionId] = {"condition": condition, "callback": callback, "id": subscriptionId}
        return subscriptionId

    def unsubscribe(self, subscriptionId):
        del self._listeners[subscriptionId]

    def suspendEvents(self):
        self._eventsSuspended = True

    def resumeEvents(self):
        self._eventsSuspended = False
        while len(self._recordedEvents) > 0:
            (eventName, resource, payload, delayed) = self._recordedEvents.pop()
            self.publish(eventName, resource, payload, delayed)

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

    def getEventCondition(self, eventName):
        raise Exception("Not implemented")
    def getEventNames(self):
        raise Exception("Not implemented")

    @staticmethod
    def isActionHandler(eventName):
        return eventName in ["run", "register", "update", "delete", "activate"]

class Repository(object):
    LOG = logging.getLogger("gears.Repository")
    def __init__(self, engine, repositoryPath):
        self._repositoryPath = repositoryPath
        self._engine = engine

    def scan(self):
        from engine.handlers import FileHandler
        from engine.resources import FileResource
        self.LOG.info("Scanning %s" % self._repositoryPath)

        self._engine.eventBus.suspendEvents()

        try:
            for dirName, subdirList, fileList in os.walk(self._repositoryPath):
                for fileName in fileList:
                    fullPath = os.path.join(dirName, fileName)
                    if not FileHandler.isHandler(fileName):
                        self._engine.resourceManager.addResource(FileResource(fullPath))
                    else:
                        self._engine.handlerManager.registerHandler(FileHandler(self._engine, fullPath))
        finally:
            self.LOG.info("Finished scanning - resuming events")
            self._engine.eventBus.resumeEvents()
            self._engine.resourceManager.dump()