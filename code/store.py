import uuid
#import redis
import json


class DictStoreBackend(object):
    """
    In memory back-end for storing data.
    NOTE: don't use this is application runs with concurrency.
    """

    items = None

    def __init__(self):
        self.items = dict()

    def set(self, key, data):
        self.items[key] = data

    def get(self, key):
        return self.items[key]

    def update(self, key, data):
        current = self.get(key)
        self.set(key, current.update(data))

    def delete(self, key):
        del self.items[key]

'''
class RedisStoreBackend(object):
    """
    Redis back-end for storing data.
    """

    r = None

    def __init__(self):
        self.r = redis.StrictRedis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=0)

    def set(self, key, data):
        self.r.set(key, json.dumps(data))

    def get(self, key):
        response = self.r.get(key)
        if response is None:
            return None
        return json.loads(response.decode("utf-8"))

    def update(self, key, data):
        current = self.get(key)
        self.set(key, current.update(data))

    def delete_process(self, key):
        self.r.delete(key)
'''