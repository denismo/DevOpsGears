from engine.handlers import SQSHandler
from engine import Engine, ResourceCondition, Resource, EventCondition
import logging
from boto import sqs
import threading
from time import sleep

__author__ = 'Denis Mikhalkin'

import unittest
import boto

class Test(unittest.TestCase):
    def tearDown(self):
        if hasattr(self, "engine"):
            self.engine.stop()

    def testEC2(self):
        logging.basicConfig()
        logging.root.setLevel(logging.INFO)
        engine = Engine({"aws_properties": {"profile_name":"packer"}})
        self.engine = engine
        instance = Resource("testinstance", "ec2instance", engine.resourceManager.root,
                            behavior="engine.handlers.EC2InstanceHandler",
                            desc={"region": "ap-southeast-2", "image-id": "ami-63f79559", "instance-type": "t2.micro",
                                  "key-name": "SydneyEC2", "security-groups": ["default"]})
        engine.resourceManager.addResource(instance)

        engine.start()
        assert engine.resourceManager.getResource("root").isState("ACTIVATED")
        instance.waitForState("ACTIVATED", 60)
        assert engine.resourceManager.getResource("testinstance").isState("ACTIVATED")

