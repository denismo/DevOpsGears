from handlers import SQSHandler
from runner import Engine, ResourceCondition, Resource, EventCondition
import logging
from boto import sqs
import threading
from time import sleep

__author__ = 'Denis Mikhalkin'

import unittest

class Test(unittest.TestCase):
    def testSQS(self):
        logging.basicConfig()
        logging.root.setLevel(logging.INFO)
        engine = Engine({"aws_properties": {"profile_name":"pam"}})
        engine.handlerManager.registerSubscribe(SQSHandler(engine), ResourceCondition(resourceType="sqs"))
        engine.resourceManager.addResource(Resource("testqueue", "sqs", engine.resourceManager.root, desc=dict(region="ap-southeast-2", queueName="testqueue"), raisesEvents=["received"]))
        condition = threading.Condition()
        engine.handlerManager.registerOn(TestHandler(condition), EventCondition(eventName="received", resourceType="sqs"))

        conn = sqs.connect_to_region("ap-southeast-2")
        queue = conn.lookup("testqueue")
        queue.write(queue.new_message("test"))
        with condition:
            condition.wait(120)
        print "Finished"

class TestHandler(object):

    def __init__(self, condition):
        self.condition = condition

    def handleEvent(self, eventName, resource, payload):
        if eventName == "received" and resource.type == "sqs":
            print "Received message in SQS queue"
            with self.condition:
                self.condition.notify()
