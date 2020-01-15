"""Tests for the Porthole Python Client.

Tests are currently all included in this file. There is one integration test
which needs to be run against a running Porthole server. The rest are unit
tests.

"""

import inspect
import os
import sys
import shutil
import json
import distutils.spawn
from pprint import pprint, pformat
import subprocess
import time

from nose.tools import assert_raises, eq_

if sys.version_info > (3, 3):
    from unittest.mock import MagicMock, Mock, patch
else:
    from mock.mock import MagicMock, Mock, patch

from emacs_porthole import core, exceptions, json_rpc
from emacs_porthole.core import (
    validate_server_name,
    _session_file_path,
    _session_from_file,
    ServerNotRunningError,
    _cache_session,
    _construct_address,
    _prepare_request,
    _send_request,
    _session_from_cache,
    _session_info_cached,
)


test_file = inspect.stack()[0][1]
TESTS_DIR = os.path.dirname(test_file)
# Directory for temporary files for the tests
TESTS_TEMP = os.path.join(TESTS_DIR, "tests_tmp")


def setup():
    if not os.path.isdir(TESTS_TEMP):
        os.mkdir(TESTS_TEMP)


def teardown():
    if os.path.isdir(TESTS_TEMP):
        shutil.rmtree(TESTS_TEMP)


def _check_ping(port):
    """Test helper to check if a port pings back."""
    response = subprocess.check_call(["nc", "-z", "localhost", str(port)])
    return response == 0


def _raise_unexpected(error):
    """Test helper to handle an _raise_unexpected error.

    Raised another and prints a breakdown of the original.

    """
    raise RuntimeError(
        "An unexpected error was raised. Class: {}. Info: "
        "\n{}".format(type(error), pformat(vars(error)))
    )


class Test_validate_server_name:
    def test_empty_name(self):
        # Should not raise an error. That's it.
        validate_server_name("this-is-972-a-test")

    def test_invalid_name_1(self):
        assert_raises(ValueError, validate_server_name, "&")

    def test_invalid_name_2(self):
        assert_raises(ValueError, validate_server_name, "this_is_a_test")

    def test_empty_name(self):
        assert_raises(ValueError, validate_server_name, "")


class Test__session_from_file:
    def test_invalid_server(self):
        """Test a server that isn't running."""
        # Test a server that can't exist, because it has invalid characters.
        assert_raises(
            ServerNotRunningError, _session_from_file, "this_server_cannot_exist"
        )

    def test_valid_server(self):
        dummy_file_path = os.path.join(TESTS_TEMP, "dummy_session.json")
        dummy_data = {"port": 10, "username": "abcde", "password": "edcba"}
        with open(dummy_file_path, "w") as f:
            json.dump(dummy_data, f)
        with patch(
            "emacs_porthole.core._session_file_path", return_value=dummy_file_path
        ):
            assert _session_from_file("any_name") == dummy_data


class Test_call_against_real_server:
    """Many tests against a real Porthole server.

    These require a Porthole server to be running.

    The server should be called "python-test-server". It should have the
    function "+" exposed. Start it by evaluating the following (place point
    after, then \"C-x C-e\"):

    (porthole-start-server "python-test-server" :exposed-functions '(+ sleep-for))

    To stop, evaluate:

    (porthole-stop-server "python-test-server")

    This isn't really a unit test. It's an integration test that implicitly
    tests the whole package.

    """

    SERVER_NAME = "python-test-server"

    def read_session_from_file(self):
        """Read the session from file, with a meaningful error.

        This basically just exists to remind the developer to start the test
        server.

        """
        # HACK: This is a hacky way of bugging developers
        try:
            return core._session_from_file(self.SERVER_NAME)
        except exceptions.ServerNotRunningError as e:
            raise RuntimeError(
                "Could not read the server file. MAKE SURE YOU START THE "
                "SERVER FOR THIS TEST. See the "
                "`Test_call_against_real_server` docstring for details."
            )

    def test_call_valid_call(self):
        """Test a valid call, that should return."""
        # Bug the user if the server isn't running
        self.read_session_from_file()
        try:
            result = core.call(self.SERVER_NAME, "+", [1, 2, 3])
        except Exception as e:
            _raise_unexpected(e)
        eq_(result, 6)

    def test_call_hidden_function(self):
        """Test that `call` correctly receives JSON-RPC error responses.

        Other JSON-RPC errors won't be prompted. This is fine.

        """
        # Bug the user if the server isn't running
        self.read_session_from_file()
        try:
            # Do this call twice. First, check the exception, then check the
            # response structure.
            assert_raises(
                core.json_rpc.MethodNotExposedError,
                core.call,
                self.SERVER_NAME,
                "insert",
                ["this is some text"],
            )
            result = core.call(self.SERVER_NAME, "insert", ["this is some text"])
            raise ValueError("Should never get here. Result: {}").format(result)
        except json_rpc.MethodNotExposedError as e:
            json_response = e.raw_response
            assert isinstance(json_response, dict), json_response
            assert "jsonrpc" in json_response, json_response
            assert json_response["jsonrpc"] == "2.0", json_response
            assert "error" in json_response, json_response
            assert json_response["error"] == e.error, e
            error = e.error
            assert isinstance(error, dict), json_response
            assert "data" in error, json_response
            assert "code" in error, json_response
            assert error["code"], json_response
        except Exception as e:
            _raise_unexpected(e)

    def test_call_invalid_server(self):
        # Test a call to an invalid server. This shouldn't get past the name
        # check.
        assert_raises(ValueError, core.call, "server_that_cant_exist", "+", 1)

    def test_call_nonexistant_server(self):
        # Make sure this server actually doesn't exist!
        assert_raises(
            core.ServerNotRunningError,
            core.call,
            "nonexistant-server-3280984",
            "+",
            [1],
        )

    def test_call_dead_but_cached(self):
        """Test a call to a server that is dead, but has its info cached."""
        core._cache_session(
            "nonexistant-server-329384",
            {"port": 23098, "username": "1240981248", "password": "304130984184"},
        )
        # Make sure this server actually doesn't exist!
        assert_raises(
            core.ServerNotRunningError, core.call, "nonexistant-server-329384", "+", [1]
        )

    def test_wrong_port_in_cache(self):
        """Test an out of date cache, in this case a wrong port."""
        # First, ensure the info is cached.
        session = self.read_session_from_file()
        # We ensure the session was loaded
        assert "port" in session, session
        core._cache_session(self.SERVER_NAME, session)
        # Now modify the cache to be wrong. It should fail to connect, then
        # reload from disk.
        core._server_info_cache[self.SERVER_NAME]["port"] -= 1
        try:
            result = core.call(self.SERVER_NAME, "+", [1, 2, 3])
        except Exception as e:
            _raise_unexpected(e)
        eq_(result, 6)

    def test_wrong_username_in_cache(self):
        """Test an out of date cache, in this case a wrong username.

        This is designed to test out-of-date credentials in general. Porthole
        authorization itself is tested in the Elisp package.

        """
        # First, ensure the info is cached.
        session = core._session_from_file(self.SERVER_NAME)
        # We ensure the session was loaded
        assert "username" in session, session
        core._cache_session(self.SERVER_NAME, session)
        # Now modify the cache to be wrong. It should fail to connect, then
        # reload from disk.
        core._server_info_cache[self.SERVER_NAME]["username"] = "wrong"
        try:
            result = core.call(self.SERVER_NAME, "+", [1, 2, 3])
        except Exception as e:
            _raise_unexpected(e)
        eq_(result, 6)

    def test_tcp_squatter(self):
        """Test what happens when the call contacts the wrong HTTP process.

        The cache may be out of date. Most of the time, it will point to a dead
        socket, which is easy to deal with. In rare cases, a different TCP
        process may have started on that socket.

        This test checks that the call can cope with a cache that points to a
        different TCP process. The new process may respond with mangled
        information, or it may time out. Either way, the session should be
        re-read from disk, at which point it should succeed.

        """
        # Load the actual server's info
        session = self.read_session_from_file()
        # We ensure the session was loaded
        assert "port" in session, session
        # Cache it
        core._cache_session(self.SERVER_NAME, session)
        one_port_down = session["port"] - 1
        assert distutils.spawn.find_executable(
            "nc"
        ), "Netcat is needed to test TCP clashes. Could not find `nc`."
        # Open a dummy netcat TCP process on the next port down. It's possible
        # to get a port clash here - if we do, that's ok. It doesn't mean
        # `core.py` is broken, it just means we were unlucky. Re-run
        # the tests a few times until you hit a free pair.
        nc_process = subprocess.Popen(["nc", "-l", "{}".format(one_port_down)])
        # Give it a bit to start
        time.sleep(0.5)
        # Make sure it's running
        assert _check_ping(one_port_down), "The nc server didn't seem to start."
        try:
            # Now modify the cache to point to the NC process. It should
            # connect, then fail, then retry successfully from disk.
            core._server_info_cache[self.SERVER_NAME]["port"] = one_port_down
            result = core.call(self.SERVER_NAME, "+", [1, 2, 3])
        finally:
            # Clean up the nc process
            nc_process.kill()
        eq_(result, 6)

    def test_http_squatter(self):
        """Test what happens when the call contacts the wrong HTTP process.

        The cache may be out of date. Most of the time, it will point to a dead
        socket, which is easy to deal with. In rare cases, a different TCP
        process may have started on that socket.

        This test checks that the call can cope with a cache that points to a
        different HTTP server. A server like that will still respond to HTTP
        requests, so it needs to be handled differently to an arbitrary TCP
        process.

        """
        # Load the actual server's info
        session = self.read_session_from_file()
        # We ensure the session was loaded
        assert "port" in session, session
        # Cache it
        core._cache_session(self.SERVER_NAME, session)
        # Use a different port to the NC test, in case the NC process didn't end.
        two_ports_down = session["port"] - 2
        assert distutils.spawn.find_executable(
            "nc"
        ), "Netcat is needed to test TCP clashes. Could not find `nc`."
        # Open a dummy netcat HTTP server on the next port down. It's possible
        # to get a port clash here - if we do, that's ok. It doesn't mean
        # `core.py` is broken, it just means we were unlucky. Re-run
        # the tests a few times until you hit a free pair.
        if sys.version_info >= (3,):
            http_process = subprocess.Popen(
                ["python3", "-m", "http.server", "{}".format(two_ports_down)]
            )
        else:
            http_process = subprocess.Popen(
                ["python2", "-m", "SimpleHTTPServer", "{}".format(two_ports_down)]
            )
        # Give it a bit to start (HTTP servers are slow to start. This is an
        # unreliable heuristic - bump the number up if it's failing.)
        time.sleep(0.5)
        # Make sure it's running
        assert _check_ping(two_ports_down), "The HTTP server didn't seem to start."
        try:
            # Now modify the cache to point to the bad HTTP process. It should
            # connect, return an error, then retry successfully from disk.
            core._server_info_cache[self.SERVER_NAME]["port"] = two_ports_down
            result = core.call(self.SERVER_NAME, "+", [1, 2, 3])
        finally:
            # Clean up the nc process
            http_process.kill()
        eq_(result, 6)

    def test_timeout(self):
        # Tell Emacs to sleep for slightly longer than the timeout. Thus Emacs
        # won't respond within the allotted time and it should trigger a
        # timeout.
        assert_raises(
            core.TimeoutError,
            core.call,
            self.SERVER_NAME,
            "sleep-for",
            [1],
            timeout=0.1,
        )
        # Now we wait, to ensure Emacs is no longer busy when we run the next
        # test.
        time.sleep(1.1)


class Test_valid_response:
    def test_valid_result(self):
        # Use a value of "None" for the result to try and trip it up. Same for
        # id.
        response = {"jsonrpc": "2.0", "result": None, "id": None}
        assert json_rpc.valid_response(response)

    def test_string_id(self):
        response = {"jsonrpc": "2.0", "result": None, "id": "sdflkjdjfk"}
        assert json_rpc.valid_response(response)

    def test_int_id(self):
        response = {"jsonrpc": "2.0", "result": None, "id": 29471507}
        assert json_rpc.valid_response(response)

    def test_valid_error(self):
        response = {
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "some message", "data": None},
            "id": None,
        }
        assert json_rpc.valid_response(response)

    def test_no_jsonrpc(self):
        response = {"result": "a result", "id": 29471507}
        assert not json_rpc.valid_response(response)

    def test_no_result_or_error(self):
        response = {"jsonrpc": "2.0", "id": 29471507}
        assert not json_rpc.valid_response(response)

    def test_no_id(self):
        response = {"jsonrpc": "2.0", "result": "a result"}
        assert not json_rpc.valid_response(response)


class Test_valid_response_string:
    def test_valid(self):
        response_string = '{"jsonrpc": "2.0", "result": null, "id": null}'
        assert json_rpc.valid_response_string(response_string)

    def test_valid_json_invalid_response(self):
        response_string = '{"jsonrpc": "2.0", "salkjslfjk": null, "id": null}'
        assert not json_rpc.valid_response_string(response_string)

    def test_invalid_json(self):
        # Use a value of "None" for the result to try and trip it up. Same for
        # id.
        response_string = "askjldk"
        assert not json_rpc.valid_response_string(response_string)

    def test_not_a_string(self):
        assert_raises(ValueError, json_rpc.valid_response_string, {})


class Test__valid_json_rpc_error:
    def test_valid(self):
        error = {"code": -32600, "message": "some message", "data": None}
        assert json_rpc._valid_error(error)

    def test_no_code(self):
        error = {"message": "some message.", "data": None}
        assert not json_rpc._valid_error(error)

    def test_no_message(self):
        error = {"code": -32600, "data": None}
        assert not json_rpc._valid_error(error)

    def test_no_data(self):
        error = {"code": -32600, "message": "some message."}
        assert not json_rpc._valid_error(error)

    def test_not_dict(self):
        error = ["code", "message", "data"]
        assert not json_rpc._valid_error(error)


@patch("emacs_porthole.core._generate_unique_id", return_value="test_id")
class Test__prepare_request:
    # "id" will be random - override it to make it predictable.
    def test_with_args(self, patched):
        target = {
            "jsonrpc": "2.0",
            "method": "test-method",
            "params": [1, 2, 3],
            "id": "test_id",
        }
        request = _prepare_request("test-method", [1, 2, 3])
        eq_(request, target)

    def test_no_args(self, patched):
        target = {
            "jsonrpc": "2.0",
            "method": "test-method-2",
            "params": [],
            "id": "test_id",
        }
        request = _prepare_request("test-method-2", [])
        eq_(request, target)

    def test_invalid_method(self, patched):
        assert_raises(ValueError, _prepare_request, 65, [])


class Test__construct_address:
    def test_simple(self):
        eq_(_construct_address(2345), "http://127.0.0.1:2345")


# TODO: Swap both of these to `assert_called_with`
@patch("emacs_porthole.core._send_request_from_cache", return_value="cache")
@patch("emacs_porthole.core._send_request_from_disk", return_value="disk")
class Test__send_request:
    @patch("emacs_porthole.core._session_info_cached", return_value=True)
    def test_cached(self, *patched):
        eq_(_send_request("dummy_server", "dummy_json"), "cache")

    @patch("emacs_porthole.core._session_info_cached", return_value=False)
    def test_not_cached(self, *patched):
        eq_(_send_request("dummy_server", "dummy_json"), "disk")


class Test__session_info_cached:
    # TODO: Swap both of these to with
    def test_cached(self):
        core._server_info_cache = {"cache-test-server": "dummy_value"}
        assert _session_info_cached("cache-test-server")

    def test_not_cached(self):
        core._server_info_cache = {"cache-test-server": "dummy_value"}
        assert not _session_info_cached("another-server")


class Test__cache_session:
    def test_simple(self):
        core._server_info_cache = {}
        _cache_session("caching-test-server", "dummy_info")
        assert "caching-test-server" in core._server_info_cache
        eq_(core._server_info_cache["caching-test-server"], "dummy_info")


class Test__session_from_cache:
    def test_simple(self):
        core._server_info_cache = {"reading-test-server": "dummy_info"}
        eq_(_session_from_cache("reading-test-server"), "dummy_info")
