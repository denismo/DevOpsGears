__author__ = 'Denis Mikhalkin'

class ResultObj(object):
    def __init__(self, result = None):
        self._result = result
        self._failureCallback = None
        self._successCallback = None

    def success(self, callback):
        if self._result == True:
            callback()
        elif self._result is None:
            self._successCallback = callback
        return self

    def failure(self, callback):
        if self._result == False:
            callback()
        elif self._result is None:
            self._failureCallback = callback
        return self

    def trigger(self, result=None):
        self._result = result if result is not None else self._result
        if self._result:
            if self._successCallback is not None: self._successCallback()
        elif self._failureCallback is not None:
            self._failureCallback()
        return self

    def append(self, obj):
        if self._result is not None:
            self._result = self._result and obj._result
        else:
            self._result = obj._result
        return self