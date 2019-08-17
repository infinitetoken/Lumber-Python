import requests, traceback

def init(token):
    return Lumber(token)

class Lumber:

    url = 'https://api.lumber.cloud/logs'

    def __init__(self, token):
        self.token = 'Bearer ' + token

    def log(self, message, code=None, level=0):
        self.print(message, level)
        trace = traceback.extract_stack(limit=3)
        payload = {
            'code': code,
            'level': level,
            'message': message,
            'line': trace[0][1],
            'method': trace[0][2]
        }
        headers = {'Authorization': self.token}
        response = requests.post(Lumber.url, json=payload, headers=headers)
        return response

    def print(self, message, level=0):
        if level == 1:
            print(u'\x1b[34m{}\x1b[39m'.format(message))
        elif level == 3:
            print(u'\x1b[33m{}\x1b[39m'.format(message))
        elif level == 4:
            print(u'\x1b[31m{}\x1b[39m'.format(message))
        elif level == 5:
            print(u'\x1b[38;5;208m{}\x1b[39m'.format(message))
        else:
            print(message)

    def info(self, message, code=None):
        response = self.log(message, code)

    def debug(self, message, code=None):
        response = self.log(message, code, 1)

    def verbose(self, message, code=None):
        response = self.log(message, code, 2)

    def warning(self, message, code=None):
        response = self.log(message, code, 3)

    def error(self, message, code=None):
        response = self.log(message, code, 4)

    def critical(self, message, code=None):
        response = self.log(message, code, 5)
