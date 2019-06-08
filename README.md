<p align=center>
    <img src="media/logo.png" alt="Porthole Python logo" />
</p>

<h1 align=center>Porthole Python Client</h1>

<p align=center>Python client for Emacs RPC servers started with <a href="https://github.com/jcaw/porthole">Porthole</a>.</p>

<p align=center>
 :sailboat:
</p>

---

<!-- ## What is this Package? -->

[Porthole](https://github.com/jcaw/porthole) lets you start RPC servers in
Emacs. These servers allow Elisp to be invoked remotely via HTTP requests.

This is a client written in Python that makes Porthole calls effortless. You only need one line:

```python
result = emacs_porthole.call(server="my-server", method="insert", params=["Some text to insert."])
```

That's it. The text will be inserted into Emacs, and the result of the operation returned. 

---

This README isn't complete yet. More coming soon (within the next couple of days). This client should be published on PyPi soon, at which point you will be able to `pip install emacs_porthole`.
