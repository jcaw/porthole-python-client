# Contributing

Contributions are welcome. Just make a pull request! 

## Pull Request Process

1. Format your code with the [black](https://github.com/python/black) auto-formatter.
2. Open a pull request against the [develop](https://github.com/jcaw/porthole-client-python/tree/develop) branch.

That's it!

Please pull against the [develop](https://github.com/jcaw/porthole-client-python/tree/develop) branch only. Changes will be
merged into master once they're determined to be stable.

If your change affects the user experience, you can update
[README.md](tree/develop/README.md), but it's not mandatory. Functionality is
more important than documentation - I can update the README.

## Formatting

Code is formatted with the [black](https://github.com/python/black)
auto-formatter because manual formatting is a waste of time. Make sure your code
has been blackened before submission. `python-black-on-save-mode` from
[emacs-python-black](https://github.com/wbolster/emacs-python-black) will
blacken your code automatically.

## Versioning

Don't bump the version in your pull request - the version will be bumped when
pushed to master. This project uses the [Semantic
Versioning](https://semver.org/) scheme (version 2.0.0). 
