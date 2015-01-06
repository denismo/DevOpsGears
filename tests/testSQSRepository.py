__author__ = 'Denis Mikhalkin'

from engine.handlers import SQSHandler
from engine import Engine, ResourceCondition, Resource, EventCondition
import logging
from boto import sqs
import threading
from time import sleep

import unittest

class TestSQSRepository(unittest.TestCase):
    def test(self):
        logging.basicConfig()
        logging.root.setLevel(logging.INFO)
        engine = Engine({"aws_properties": {"profile_name":"pam"}, "repositoryPath":"/home/denismo/Documents/WS/DevOpsGears/repositories/sqsRepository"})
        # engine = Engine({"aws_properties": {"profile_name":"pam"}, "repositoryPath":"E:\\WS\\Python\\DevOpsGears\\repositories\\sqsRepository"})

        condition = threading.Condition()

        conn = sqs.connect_to_region("ap-southeast-2")
        queue = conn.lookup("testqueue")
        queue.write(queue.new_message("test"))
        with condition:
            condition.wait(120)
        print "Finished"

if __name__ == '__main__':
    unittest.main()
