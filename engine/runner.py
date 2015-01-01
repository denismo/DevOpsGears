__author__ = 'Denis Mikhalkin'

import json

DEFAULT_SUBSCRIBE_PERIOD = 60 # 1 minute in seconds

class Runner(object):
    resourceManager = None
    """:type ResourceManager"""
    eventBus = None
    """:type EventBus"""
    handlerManager = None
    """:type HandlerManager"""

    def __init__(self, config):
        sqs = SQS("ap-southeast-2", "GitChanges")
        self.resourceManager.addResource(sqs)
        sqs.subscribe("GitChanged")
        self.handlerManager.registerOn(GitHandler(), EventCondition("GitChanged"))

class HandlerManager(object):
    pass

class EventCondition(object):
    def __init__(self, eventName, resourcePattern=None):
        self.eventName = eventName
        self.resourcePattern = resourcePattern

class Resource(object):
    pass

class Scheduler(object):
    pass

class EventBus(object):
    pass

class SQS(Resource):
    scheduler = None
    """:type Scheduler"""
    eventBus = None
    """:type EventBus"""
    queueName = ""
    region = ""

    def __init__(self, region, queueName):
        self.region = region
        self.queueName = queueName

    def subscribe(self, eventName):
        conn = sqs.connect_to_region(self.region)

        def poll():
            queue = conn.lookup(self.queueName)
            msg = queue.read()
            if msg is not None:
                queue.delete_message(msg)
                eventBus.publish(eventName, self, msg.get_body())

        self.scheduler.schedule(poll, DEFAULT_SUBSCRIBE_PERIOD)

class FileHandler(object):
    eventBus = None
    """:type EventBus"""

    def __init__(self, fileName):
        self.file = fileName
        self.getEventCondition()

    def getEventCondition(self):
        if hasattr(self, "condition"):
            return self.condition
        if self.file[0:3] == "on.":
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
            firstLine = opened.readline().trim()
            return firstLine is not None and firstLine[0:2] == "#!"
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
                return
            except OSError:
                # TODO Log error
                pass # Unable to run the script - let's try a run handler

        self.eventBus.publish("run", self, {resource: resource, payload: payload})

    def systemExecute(self, resource, payload):


class GitHandler(object):
    handlerManager = None
    """:type HandlerManager"""
    resourceManager = None
    """:type ResourceManager"""

    def handleEvent(self, eventName, resource, payload):
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