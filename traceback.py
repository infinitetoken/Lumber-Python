# import traceback
#
# def trace():
#     trace = traceback.extract_stack(limit=3)
#     # print('line', trace[0][1], 'method', trace[0][2])
#     t = dict()
#     t['line'] = trace[0][1]
#     t['method'] = trace[0][2]
#     return t
#
# def lumber(message):
#     t = trace()
#     print(t['line'])
#
# def myMethod():
#     try:
#         thisshit()
#     except NameError:
#         # print(err)
#         lumber('NameError: caught name error')
#
# def two():
#     myMethod()
# def one():
#     two()
#
#
# one()
