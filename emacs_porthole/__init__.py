#!/usr/bin/env python3

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

# TODO: uuid has a dodgy implementation in old versions. Should we use
#   something else?
import uuid


# Filename part the session info file
SESSION_FILE = "session.json"


_server_info_cache = {}


class PortholeCallError(RuntimeError):
    """Base class for all errors that might occur during a Porthole call."""


class PortholeConnectionError(PortholeCallError,
                              requests.exceptions.RequestException):
    """Base class for all Porthole connection-related errors."""

    def __init__(self, message, underlying_error=None):
        super().__init__(message)
        self.underlying_error = underlying_error


class ServerNotRunningError(PortholeConnectionError,
                            requests.exceptions.ConnectionError):
    """Error to be raised when the server does not appear to be running."""


class StrangeResponseError(ServerNotRunningError):
    """Error that indicates a strange response was received.

    A strange response is assumed to come from something other than Porthole.
    This implies the Porthole server is not running.

    The original response will be attached to this error, in the `response`
    member.

    """

    def __init__(self, message, response):
        super().__init__(message)
        self.response = response


class TimeoutError(PortholeConnectionError, requests.exceptions.Timeout):
    """Error that indicates the request timed out.

    Since Emacs is single-threaded, a timeout may simply mean Emacs is busy.
    Don't assume this means the server is not running.

    """


class JsonRpcError(PortholeCallError):
    """Error meaning a JSON-RPC 2.0 error response was returned.

    This means there was an error processing JSON-RPC 2.0 request within Emacs,
    after the HTTP handler had extracted it from the HTTP request.

    The `response` member in this error carries the decoded JSON-RPC 2.0
    response object. This will be a dictionary with three keys, "jsonrpc",
    "error" and "id".

    If this response wraps an underlying Elisp error, details of that error
    will be attached. They will be under
    `response["error"]["data"]["underlying-error"]`.

    """

    # TODO: Explain the data structure of this error.
    def __init__(self, response):
        super().__init__("A JSON-RPC 2.0 Error response was received.")
        if not _valid_json_rpc_response(response):
            raise ValueError(
                "Response was not a valid JSON-RPC 2.0 response. Please "
                "validate the response before attempting to attach it to "
                "this error."
            )
        # Most important information is the error, but store the whole response
        # just in case the user wants it.
        #
        # We assume the response has already been validated as an error.
        self.json_rpc_error = response["error"]
        self.json_rpc_response = response


class HTTPError(PortholeCallError):
    def __init__(self, message, response):
        super().__init__(message)
        self.response = response
        self.code = response.status_code
        self.content = response.text
        self.content_type = response.content_type


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
        return get_temp_folder_linux()
    elif system.lower() == "windows":
        # Windows is easy. %TEMP% should always exist, and be a user-restricted
        # directory.
        return os.environ("TEMP")
    elif system.lower() == "mac":
        return os.path.join(os.environ("HOME"), "Library")
    else:
        # On unknown systems, Porthole falls back to the same method it uses on
        # Linux.
        return get_temp_folder_linux()


# Porthole stores server sessions in its own subdirectory.
TEMP_FOLDER = os.path.join(_get_temp_folder(), "emacs-porthole")


# TODO: Set default timeout
def call(server_name, method, *params, timeout=None):
    """Make an RPC call to a Porthole server."""
    # TODO: Flesh out docstring
    json_rpc_response = call_raw(server_name, method, *params, timeout=timeout)
    if "result" in json_rpc_response:
            # Successful call! Return it.
        return json_rpc_response["result"]
    else:
        # Response has already been checked. It should be valid a valid
        # JSON-RPC 2.0 response.
        raise JsonRpcError(response=json_rpc_response)


def call_raw(server_name, method, *params, timeout=None):
    """Get the raw JSON-RPC response from an RPC call to Porthole."""
    validate_server_name(server_name)
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
            "HTTP response {} received.".format(response.error_code),
            code=response.error_code,
            message=response.text,
            response=response,
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
            "The session information file at \"{}\" could not be read. Assuming "
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
    return "http://localhost:{}".format(port)


def _send_request(server_name, json):
    """Send a request to `server_name`. Query details automatically."""
    if _session_info_cached(server_name):
        return _send_request_from_cache(server_name, json)
    else:
        return _send_request_from_disk(server_name, json)


def _session_info_cached(server_name):
    """Is there cached session info for server with name `server_name`?"""
    global _server_info_cache
    return server_name in _server_info_cache


def _send_request_from_cache(server_name, json):
    """Make a call to Porthole. Try to use the cache, if possible."""
    cached_session = _session_from_cache(server_name)
    response, requests_error = _try_to_post(server_name, json, cached_session)
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
            _cache_session(session_on_disk)
            respose, error = _try_to_post(server_name, request, session)
            if error:
                raise error
            else:
                return response
    else:
        # No problems. Return the response.
        return response


def _send_request_from_disk(server_name, json):
    """Make a request. Read the session info from a file, not the cache."""
    session = _session_from_file(server_name)
    response, requests_error = _try_to_post(server_name, json, session)
    if requests_error:
        # Re-raise any errors.
        raise requests_error
    else:
        _cache_session(server_name, session)
        return response


def _cache_session(server_name, session):
    global _server_info_cache
    _server_info_cache[server_name] = session


def _try_to_post(server_name, request, session):
    """Make a POST request to a Porthole server."""
    if not "port" in session:
        raise ValueError("No port number in session information.")
    address = _construct_address(session.get("port"))
    username = session.get("username")
    password = session.get("password")
    if username or password:
        auth = (username or "" , password or "")
    else:
        # TODO: Maybe disallow requests without authentication?
        auth = None
    try:
        result = requests.post(address, json=request, auth=auth)
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
        and _valid_json_rpc_response_string(response.text)
    )


def _valid_json_rpc_response_string(string):
    """Check if `string` is a valid JSON-RPC 2.0 response.

    """
    try:
        # Decode the response into JSON
        response = json.loads(string)
    except:
        # Couldn't be decoded. Definitely not valid JSON.
        return False
    return _valid_json_rpc_response(response)


def _valid_json_rpc_response(response):
    """Check if a decoded JSON object is a valid JSON-RPC 2.0 response."""
    has_id = "id" in response
    id_ = response.get("id")
    valid_id = has_id and (
        isinstance(id_, str)
        or isinstance(id_, int)
        # We also have to account for the server not being able to return an ID
        or id_ is None)
    has_result = "result" in response
    valid_error = _valid_json_rpc_error(response.get("error"))
    return (
        isinstance(response, dict)
        # We ensure the version is JSON-RPC 2.0
        and response.get("jsonrpc") == "2.0"
        and valid_id
        and (has_result or valid_error)
    )


def _valid_json_rpc_error(error):
    """Is `error` a valid error from a JSON-RPC 2.0 response object?"""
    # We just check that error has the right footprint. Don't worry about the
    # specifics. If it has the footpring, it's almost certainly JSON-RPC. We
    # aren't checking the validity of Porthole's encoding mechanisms - just
    # that we did in fact receive a JSON-RPC response.
    return (
        isinstance(error, dict)
        and "code" in error
        and "message" in error
        and "data" in error
    )
