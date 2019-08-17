from Lumber import Lumber

lumber = Lumber('b07e9f00bdfb11e9b22a4f6283021c32')

def testMethod():
    lumber.log('Log', 5)
    lumber.info('Info')
    lumber.debug('Debug')
    lumber.verbose('Verbose')
    lumber.warning('Warning')
    lumber.error('Error')
    lumber.critical('Critical')

testMethod()
