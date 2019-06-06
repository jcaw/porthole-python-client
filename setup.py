from distutils.core import setup

setup(
    name='emacs_porthole',
    version='0.1dev',
    packages=['emacs_porthole',],
    license='MIT License',
    description="Python client for the Emacs Porthole RPC server.",
    long_description=open('README.md').read(),
)
