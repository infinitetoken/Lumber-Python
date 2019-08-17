import requests, traceback

def init(token):
    return Lumber(token)

class Lumber:

    url = 'https://api.lumber.cloud/logs'

    def __init__(self, token):
        self.token = 'Bearer ' + token

    def log(self, message, level=0):
        self.print(message, level)
        trace = traceback.extract_stack(limit=3)
        payload = {
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

    def info(self, message):
        response = self.log(message)

    def debug(self, message):
        response = self.log(message, 1)

    def verbose(self, message):
        response = self.log(message, 2)

    def warning(self, message):
        response = self.log(message, 3)

    def error(self, message):
        response = self.log(message, 4)

    def critical(self, message):
        response = self.log(message, 5)
