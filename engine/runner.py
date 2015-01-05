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

# TODO: Test is not running

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
        self.LOG.info("Engine started")

class HandlerManager(object):
    LOG = logging.getLogger("gears.HandlerManager")
    handlers = dict()

    def __init__(self, engine):
        self._eventBus = engine.eventBus
        self._resourceManager = engine.resourceManager
        self._eventBus.subscribe(lambda eventName, resource, payload: True, self.handleEvent)
        self.LOG.info("HandlerManager created")

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
        self.LOG.info("ResourceManager created")

    def addResource(self, resource):
        self.LOG.info("addResource(%s)" % resource)
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
        self.LOG.info("EventBus created")
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
                    # TODO Logging

    def subscribe(self, condition, callback):
        self.LOG.info("subscribe(condition=%s)" % str(condition))
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

class Handler(object):
    LOG = logging.getLogger("gears.handlers.Handler")
    def handleEvent(self, eventName, resource, payload):
        if eventName == "create":
            return self.handleCreate(resource, payload)
        elif eventName == "subscribe":
            return self.handleSubscribe(resource, payload)
        else: self.LOG.error("Unhandled event %s on %s with %s" % (eventName, resource, payload))

    def handleCreate(self, resource, payload):
        pass
    def handleSubscribe(self, resource, payload):
        self.LOG.error("Unhandled 'subscribe' on %s with %s" % (resource, payload))
        pass

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

class SQSHandler(Handler):
    LOG = logging.getLogger("gears.handlers.SQSHandler")
    _scheduler = None
    """:type Scheduler"""
    _eventBus = None
    """:type EventBus"""

    def __init__(self, engine):
        self._eventBus = engine.eventBus
        self._scheduler = engine.scheduler
        self._aws_config = engine.config["aws_config"] if "aws_config" in engine.config else None

    def handleSubscribe(self, resource, payload):
        self.LOG.info("handleSubscribe(resource=%s, payload=%s)" % (resource, payload))
        if not resource.type == "sqs": return False

        # if self._aws_config is not None and "profile_name" in self._aws_config:
        #     conn = sqs.connect_to_region(resource.desc["region"], profile_name=self._aws_config["profile_name"])
        # else:
        conn = sqs.connect_to_region(resource.desc["region"])

        def poll():
            queue = conn.lookup(resource.desc["queueName"])
            msg = queue.read()
            if msg is not None:
                queue.delete_message(msg)
                self._eventBus.publish(payload["eventName"], resource, msg.get_body())

        self._scheduler.schedule("sqs %s poll" % (resource.desc["queueName"]), poll, DEFAULT_SUBSCRIBE_PERIOD)


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