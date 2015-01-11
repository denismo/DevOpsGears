from engine.handlers import SQSHandler
from engine import Engine, ResourceCondition, Resource, EventCondition
import logging
from boto import sqs
import threading
from time import sleep

__author__ = 'Denis Mikhalkin'

import unittest

class Test(unittest.TestCase):
    def testInit(self):
        logging.basicConfig()
        logging.root.setLevel(logging.INFO)
        engine = Engine({"aws_properties": {"profile_name":"pam"}})
        engine.handlerManager.registerSubscribe(SQSHandler(engine), ResourceCondition(resourceType="sqs"))
        engine.resourceManager.addResource(Resource("testqueue", "sqs", engine.resourceManager.root, desc=dict(region="ap-southeast-2", queueName="testqueue"), raisesEvents=["received"]))

        engine.start()
        engine.resourceManager.dump()
        assert engine.resourceManager.getResource("root").state == "ACTIVATED"
        assert engine.resourceManager.getResource("testqueue").state == "ACTIVATED"

