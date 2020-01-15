"""Client library for the Emacs Porthole RPC server.

This library is designed to make it easy to invoke Porthole RPC calls.

Just call the function `call` with the name of your server, the method, and
your parameters. This library will handle the rest.

"""

import requests
import os
import platform
import json
import re
from emacs_porthole.exceptions import (
    PortholeCallError,
    PortholeConnectionError,
    ServerNotRunningError,
    StrangeResponseError,
    TimeoutError,
    HTTPError,
)
from emacs_porthole import json_rpc

# TODO: uuid has a dodgy implementation in old versions. Should we use
#   something else?
import uuid


# Default timeout, in seconds
DEFAULT_TIMEOUT = 1
# Filename part the session info file
SESSION_FILE = "session.json"


# Dictionary mapping server names to their cached session information.
#
# The session information for each server will be a dictionary with the
# following structure:
#
# {
#     "port": port,
#     "username": username,
#     "password": password,
# }
#
# Not all members will necessarily be present.
_server_info_cache = {}


def _get_temp_folder_linux():
    """Get the temp folder on a Linux system.

    This method may also be used by unknown operating systems.

    """
    # On Linux, we prefer to use "$XDG_RUNTIME_DIR", since it is dedicated
    # to this kind of purpose. If it's not available, Porthole will create
    # a new temporary directory in the user's home dir.
    if "XDG_RUNTIME_DIR" in os.environ:
        return os.environ["XDG_RUNTIME_DIR"]
    elif "HOME" in os.environ:
        return os.path.join(os.environ["HOME"], "tmp")
    else:
        raise IOError(
            "Neither $XDG_RUNTIME_DIR or $HOME could be read. Cannot "
            "automatically query server information on this system."
        )


def _get_temp_folder():
    """Get the temp folder where session information will be stored.

    The specific folder used depends on the platform. This method returns the
    same temp folder that Porthole will use to store session information. It
    should be a folder that's only accessible to the current user.

    """
    system = platform.system()
    if system.lower() == "linux":
        return _get_temp_folder_linux()
    elif system.lower() == "windows":
        # Windows is easy. %TEMP% should always exist, and be a user-restricted
        # directory.
        return os.environ["TEMP"]
    elif system.lower() == "mac":
        return os.path.join(os.environ["HOME"], "Library")
    else:
        # On unknown systems, Porthole falls back to the same method it uses on
        # Linux.
        return _get_temp_folder_linux()


# Porthole stores server sessions in its own subdirectory.
TEMP_FOLDER = os.path.join(_get_temp_folder(), "emacs-porthole")


# TODO: Set default timeout
def call(server, method, params=[], timeout=DEFAULT_TIMEOUT):
    """Make an RPC call to a Porthole server.

    Please see the README for full usage examples and error handling.

    :param server: The name of the Porthole server.
    :type server: str
    :param method: The name of the method you want to call.
    :type method: str
    :param params: The parameters to pass to the method you want to call.
    :type params: list
    :param timeout: The amount of time, in seconds, to wait before the request
      times out.
    :type timeout: float

    """
    json_rpc_response = call_raw(server, method, params, timeout=timeout)
    if "result" in json_rpc_response:
        # Successful call! Return it.
        return json_rpc_response["result"]
    else:
        # Response has already been checked. It should be a valid JSON-RPC 2.0
        # response, so this is safe to call.
        json_rpc.raise_error(json_rpc_response)


def call_raw(server_name, method, params=[], timeout=DEFAULT_TIMEOUT):
    """Get the raw JSON-RPC response from an RPC call to Porthole.

    Please see the README for full usage examples and error handling.

    :param server: The name of the Porthole server.
    :type server: str
    :param method: The name of the method you want to call.
    :type method: str
    :param params: The parameters to pass to the method you want to call.
    :type params: list
    :param timeout: The amount of time, in seconds, to wait before the request
      times out.
    :type timeout: float

    """
    validate_server_name(server_name)
    if not isinstance(params, list):
        raise ValueError("`params` must be a list.")
    request = _prepare_request(method, params)
    try:
        response = _send_request(server_name, request)
    except requests.exceptions.ConnectionError as e:
        raise ServerNotRunningError(
            "Could not connect. The Porthole server does not appear to be running.",
            underlying_error=e,
        )
    except requests.exceptions.Timeout as e:
        raise TimeoutError(
            "Timed out while connecting to the RPC server.", underlying_error=e
        )
    except requests.exceptions.RequestException as e:
        # Other connection problems are odd. Could they be caused by another
        # process running on this TCP socket? Assume the server isn't running.
        raise ServerNotRunningError(
            "There was a strange error connecting to the server. "
            "Assuming the server is not running.",
            underlying_error=e,
        )
    if _response_ok(response):
        return response.json()
    elif response.status_code == 200:
        raise StrangeResponseError(
            "The server returned a 200 response, but it was not a valid "
            "JSON-RPC 2.0 response. Probably a different service is running "
            "on this port.",
            response=response,
        )
    else:
        raise HTTPError(
            "HTTP response {} received.".format(response.status_code), response=response
        )


# TODO: Method that calls with user-set parameters


def _session_file_path(server_name):
    """Get the file path of the session file for `server_name`."""
    return os.path.join(TEMP_FOLDER, server_name, SESSION_FILE)


def _session_from_file(server_name):
    """Read the session information for `server_name` from its session file.

    Note that this information may be out of date since we can't guarantee it
    will be cleaned up if the porthole server is killed.

    When using this function, you must account for these possibilities:

      1. The server is not running.
      2. Another process has opened a TCP socket on this port.

    """
    session_file_path = _session_file_path(server_name)
    if os.path.isfile(session_file_path):
        with open(session_file_path) as f:
            return json.load(f)
    else:
        raise ServerNotRunningError(
            'The session information file at "{}" could not be read. Assuming '
            "the server is not running.".format(session_file_path)
        )


def _generate_unique_id():
    """Generate a unique ID for the request.

    Technically, if you have more than one client connecting to the server,
    this may not be unique (although the chance of a clash is extremely low).
    But for this client, it should be.

    """
    return str(uuid.uuid4())


def validate_server_name(server_name):
    """Ensure `server-name` is a valid name for a server.

    Server names may contain only alphanumeric characters and dashes.

    """
    assert isinstance(server_name, str)
    if not re.match("^[a-zA-Z0-9-]+$", server_name):
        raise ValueError(
            "`server_name` may only contain alphanumeric characters and "
            "dashes. It may not be empty."
        )


def _prepare_request(method, params):
    if not isinstance(method, str):
        raise ValueError("`method` should be string. Was: {}".format(type(method)))
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": _generate_unique_id(),
    }


def _construct_address(port):
    # TODO: API should be on a subdirectory. E.g. /emacs-porthole-call
    # TODO: Protect against the loopback adapter not being on 127.0.0.1. Maybe
    #   resolve it up-front at an earlier point?

    # We use "127.0.0.1" directly (instead of "localhost") because on some
    # platforms resolving localhost causes a hang on each request. (I.e. it
    # tries to target the ipv6 version first, times out, then targets ipv4.)
    return "http://127.0.0.1:{}".format(port)


def _send_request(server_name, json, timeout=None):
    """Send a request to `server_name`. Query details automatically."""
    if _session_info_cached(server_name):
        return _send_request_from_cache(server_name, json, timeout=timeout)
    else:
        return _send_request_from_disk(server_name, json, timeout=timeout)


def _session_info_cached(server_name):
    """Is there cached session info for server with name `server_name`?"""
    global _server_info_cache
    return server_name in _server_info_cache


def _send_request_from_cache(server_name, json, timeout=None):
    """Make a call to Porthole. Try to use the cache, if possible."""
    cached_session = _session_from_cache(server_name)
    response, requests_error = _try_to_post(
        server_name, json, cached_session, timeout=timeout
    )
    request_seems_to_have_failed = requests_error or not _response_ok(response)
    if request_seems_to_have_failed:
        # There was a problem. Make sure we have the correct details
        # cached. If not, try again.
        session_on_disk = _session_from_file(server_name)
        cached_session_correct = cached_session == session_on_disk
        if cached_session_correct:
            if requests_error:
                # Re-raise connection errors if we were trying to connect
                # to what looks like the right server.
                raise requests_error
            else:
                # If there were no errors and it was the right server,
                # return the response.
                return response
        else:
            _cache_session(server_name, session_on_disk)
            response, error = _try_to_post(
                server_name, json, session_on_disk, timeout=timeout
            )
            if error:
                raise error
            else:
                return response
    else:
        # No problems. Return the response.
        return response


def _send_request_from_disk(server_name, json, timeout=None):
    """Make a request. Read the session info from a file, not the cache."""
    session = _session_from_file(server_name)
    response, requests_error = _try_to_post(server_name, json, session, timeout=timeout)
    if requests_error:
        # Re-raise any errors.
        raise requests_error
    else:
        _cache_session(server_name, session)
        return response


def _cache_session(server_name, session):
    global _server_info_cache
    _server_info_cache[server_name] = session


def _try_to_post(server_name, request, session, timeout=None):
    """Make a POST request to a Porthole server."""
    if not "port" in session:
        raise ValueError("No port number in session information.")
    if not timeout:
        timeout = DEFAULT_TIMEOUT
    address = _construct_address(session.get("port"))
    username = session.get("username")
    password = session.get("password")
    if username or password:
        auth = (username or "", password or "")
    else:
        # TODO: Maybe disallow requests without authentication?
        auth = None
    try:
        result = requests.post(address, json=request, auth=auth, timeout=timeout)
        return result, None
    except requests.exceptions.RequestException as e:
        return None, e


def _session_from_cache(server_name):
    """Read the cached session info for server with `server_name`.

    This method assumes there is server info cached. If not, it will raise a
    KeyError. Please check the info is cached first with
    `_session_info_cached`.

    """
    global _server_info_cache
    return _server_info_cache[server_name]


def _response_ok(response):
    """Was `response` a success, and a valid JSON-RPC 2.0 response?

    :param response: The response from an attempted call to a Porthole server.
    :type response: requests.Response

    """
    return (
        response
        and response.status_code == 200
        # TODO: Is this vulneable to capitalisation?
        and response.headers.get("Content-Type") == "application/json"
        and json_rpc.valid_response_string(response.text)
    )
