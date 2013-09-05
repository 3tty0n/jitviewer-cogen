import sys

def failout(msg, exit_status = 1):
    print("error: %s" % (msg, ))
    sys.exit(exit_status)
