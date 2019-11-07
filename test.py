from lumber import Lumber
lumber = Lumber('2f621ef0018111ea93bd6d7e7482e49b')

def testMethod():
    lumber.info('Info')
    lumber.debug('Debug')
    lumber.verbose('Verbose')
    lumber.warning('Warning')
    lumber.error('Error')
    lumber.critical('Critical')

testMethod()

# def lumber(message):
#     t = trace()
#     # print(t['line'])
#     print(t)
#
# def myMethod():
#     try:
#         lumber('NameError: caught name error')
#         # thisshit()
#     except NameError as e:
#         lumber('NameError: caught name error')
#
# def two():
#     myMethod()
# def one():
#     two()
#
#
# one()
