import os
import subprocess
from boto import sqs
from engine import EventCondition, DEFAULT_SUBSCRIBE_PERIOD, Handler, ResourceCondition
from boto import ec2
import logging

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

class FileHandler(Handler):
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

class EC2InstanceHandler(Handler):
    LOG = logging.getLogger("engine.handlers.EC2InstanceHandler")

    def __init__(self, engine):
        self._engine = engine

    def handleEvent(self, eventName, resource, payload):
        if eventName == "register":
            self.LOG.info("Handling register for " + str(resource))
            return self._validateInstance(resource)
        if eventName == "activate":
            self.LOG.info("Handling activate for " + str(resource))
            attachRes = self._tryAttach(resource)
            self.LOG.info("Attach result: " + attachRes)
            if attachRes == "running":
                self.LOG.info("Instance is running")
                return True
            elif attachRes == "starting":
                self.LOG.info("Instance is starting")
                resource.toState("PENDING_ACTIVATION")()
                self.watchInstance(resource)
                return True
            elif attachRes == "nonexisting":
                self.LOG.info("Instance is non-existant - creating")
                if self._tryCreate(resource):
                    resource.toState("PENDING_ACTIVATION")()
                    self.watchInstance(resource)
                    return True
                else:
                    return False
            else:
                return False

    def getEventNames(self):
        return ["register", "activate"]
    def getEventCondition(self, eventName):
        return ResourceCondition("ec2instance")

    def _validateInstance(self, resource):
        return hasattr(resource, "desc") and \
            "instance-type" in resource.desc and \
            "image-id" in resource.desc and \
            "key-name" in resource.desc and \
            "security-groups" in resource.desc and \
            "region" in resource.desc

    def _tryCreate(self, resource):
        conn = ec2.connect_to_region(resource.desc["region"])
        reservation = conn.run_instances(image_id = resource.desc["image-id"], min_count= 1, max_count=1,
                           key_name=resource.desc["key-name"], security_groups=resource.desc["security-groups"],
                           instance_type=resource.desc["instance-type"])
        print reservation
        return reservation.instances is not None and len(reservation.instances) > 0
        # TODO How to determine whether it was created?

    def getInstanceState(self, resource):
        conn = ec2.connect_to_region(resource.desc["region"])
        instances = conn.get_only_instances(filters={"Name":resource.name})
        if instances is not None and len(instances) == 1:
            instance = instances[0]
            return instance.state.name
        else:
            return None

    def _tryAttach(self, resource):
        state = self.getInstanceState(resource)
        if state == "running":
            return "running"
        elif state in ["pending", "stopped"]:
            return "starting"
        elif state is None:
            return "nonexisting"
        else:
            return "unavailable"

    def watchInstance(self, resource):
        handle = []
        def monitor():
            state = self.getInstanceState(resource)
            self.LOG.info("Instance %s state is %s" % (resource, state))
            if state == "running":
                self._engine.scheduler.unschedule(handle[0])
                self._engine.eventBus.publish("activated", resource)
        handle.append(self._engine.scheduler.schedule("EC2 monitor", monitor, 10))

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

