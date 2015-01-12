import os
import subprocess
from boto import sqs, logging
from engine import EventCondition, DEFAULT_SUBSCRIBE_PERIOD, Handler

__author__ = 'Denis Mikhalkin'

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
        return True

    def getEventNames(self):
        return ["subscribe"]

    def getEventCondition(self, eventName):
        if not eventName == "subscribe": return None
        return EventCondition(eventName, "sqs")

class FileHandler(object):
    LOG = logging.getLogger("gears.handlers.FileHandler")
    _eventBus = None
    """:type EventBus"""

    def __init__(self, engine, fileFullPath):
        self._engine = engine
        self._eventBus = engine.eventBus
        self.fullPath = fileFullPath
        self.createCondition()

    def createCondition(self):
        # TODO Other types of conditions (default actions like "register")
        fileName = os.path.basename(self.fullPath)
        if fileName.startswith("on."):
            parts = fileName.split(".")
            self.condition = EventCondition()
            if len(parts) > 2:  # contains at least event name
                self.condition.eventName = parts[1]
                if len(parts) > 3:  # contains resource type
                    self.condition.resourceType = parts[2]
                    if len(parts) > 4:  # contains resource name
                        self.condition.resourceName = parts[3]
            if len(parts) > 1:
                self.type = parts[-1]

    def getEventCondition(self, eventName):
        if not eventName == self.condition.eventName: return None
        return self.condition

    def getEventNames(self):
        return [self.condition.eventName]

    def isRunnable(self):
        opened = file(self.fullPath)
        try:
            firstLine = opened.readline().strip()
            return firstLine is not None and firstLine.startswith("#!")
        finally:
            opened.close()

    @staticmethod
    def isHandler(fileName):
        (head, _, tail) = fileName.partition(".")
        return head in ["on", "run", "register", "update", "delete", "activate"]

    def handleEvent(self, eventName, resource, payload):
        if eventName == self.condition.eventName:
            self.runHandler(resource, payload)

    def runHandler(self, resource, payload):
        self.LOG.info("Running file handler %s on %s with %s" % (self.fullPath, resource, payload))
        if self.isRunnable():
            try:
                self.systemExecute(resource, payload)
                # TODO Handle return code
                return
            except OSError:
                self.LOG.exception("-> error invoking system process")

        # self._eventBus.publish("run", self, {"resource": resource, "payload": payload})

    def systemExecute(self, resource, payload):
        return subprocess.call([self.fullPath, self.condition.eventName], env={"RESOURCE": str(resource), "PAYLOAD": str(payload)})

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