import os
import yaml
from runner import Resource

__author__ = 'Denis Mikhalkin'

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

