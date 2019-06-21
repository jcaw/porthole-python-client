import sys


python2 = sys.version_info < (3,)


def is_string(var):
    """Check if `var` is a string (or unicode)."""
    target = (str, unicode) if python2 else str
    return isinstance(var, target)
