from distutils.core import setup

setup(
  name = "Porthole Python Client",
  packages = ["emacs_porthole"],
  version = "0.1dev",
  license="MIT",
  description = "Python client for the Emacs Porthole RPC server.",
  long_description=open('README.md').read(),
  author = 'GitHub user "Jcaw"',
  author_email = "toastedjcaw@gmail.com",
  url = "https://github.com/jcaw/porthole-python-client",
  download_url = "https://github.com/jcaw/porthole-python-client/archive/v_01dev.tar.gz",
  keywords = [
      "emacs",
      "rpc",
      "json-rpc",
      "remote procedure call",
      "elisp",
      "emacs-lisp"
  ],
  install_requires=[
          'requests',
          'json',
      ],
  classifiers=[
      # "3 - Alpha", "4 - Beta", "5 - Production/Stable"
      "Development Status :: 4 - Beta",
      "Intended Audience :: Developers",
      "Topic :: Text Editors :: Emacs",
      "Programming Language :: Python",
      "Programming Language :: Emacs-Lisp",
      "Natural Language :: English",
      "License :: OSI Approved :: MIT License",
      "Programming Language :: Python :: 2.7",
      "Programming Language :: Python :: 3",
  ],
)
