import os
import yaml
from engine import Resource

__author__ = 'Denis Mikhalkin'

class FileResource(Resource):
    def __init__(self, filename):
        Resource.__init__(self, os.path.splitext(filename)[0], os.path.splitext(filename)[1][1:], os.path.dirname(filename))
        self.filename = filename
        self.readProperties()

    def readProperties(self):
        self.state = Resource.STATES["INVALID"]
        if not os.path.exists(self.filename):
            return

        try:
            info = yaml.load(file(self.filename))
            if type(info) is not dict:
                return
            if "type" in info:
                self.type = info["type"]
            if "name" in info:
                self.name = info["name"]
            if "desc" in info:
                self.desc = info["desc"]
            if "behavior" in info:
                self.behavior = info["behavior"]
            self.state = Resource.STATES["DEFINED"]
        except:
            pass

