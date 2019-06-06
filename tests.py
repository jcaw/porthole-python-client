import inspect
import os
import json
from pprint import pprint, pformat
from nose.tools import assert_raises, eq_
from unittest.mock import MagicMock, Mock, patch
import emacs_porthole
from emacs_porthole import (
    validate_server_name,
    _session_file_path,
    _session_from_file,
    _valid_json_rpc_response,
    ServerNotRunningError,
)


test_file = inspect.stack()[0][1]
TESTS_DIR = os.path.dirname(test_file)
# Directory for temporary files for the tests
TESTS_TEMP = os.path.join(TESTS_DIR, "tmp")
if not os.path.isdir(TESTS_TEMP):
    os.mkdir(TESTS_TEMP)


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
        with patch("emacs_porthole._session_file_path", return_value=dummy_file_path):
            assert _session_from_file("any_name") == dummy_data


class Test_call_against_real_server:
    """Many tests against a real Porthole server.

    These require a Porthole server to be running.

    The server should be called "python-test-server". It should have the
    function "+" exposed. Start it by evaluating (place point after, then \"C-x
    C-e\"):

    (porthole-start-server "python-test-server" :exposed-functions '(+))

    To stop, evaluate:

    (porthole-stop-server "python-test-server")

    """

    SERVER_NAME = "python-test-server"

    def test_call_valid_call(self):
        """Test a valid call, that should return."""
        try:
            result = emacs_porthole.call(self.SERVER_NAME, "+", 1, 2, 3)
        except Exception as e:
            raise RuntimeError(
                "An exception was raised. Type: {}. Members: \n{}".format(
                    type(e), pformat(vars(e))
                )
            )
        eq_(result, 6)

    def test_call_hidden_function(self):
        """Test that `call` correctly receives JSON-RPC error responses.

        Other JSON-RPC errors won't be prompted. This is fine.

        """
        # Do this call twice. First, check the exception, then check the
        # response structure.
        assert_raises(
            emacs_porthole.JsonRpcError,
            emacs_porthole.call,
            self.SERVER_NAME,
            "insert",
            "this is some text",
        )
        try:
            result = emacs_porthole.call(
                self.SERVER_NAME, "insert", "this is some text"
            )
            raise ValueError("Should never get here. Result: {}").format(result)
        except emacs_porthole.JsonRpcError as e:
            json_response = e.json_rpc_response
            assert isinstance(json_response, dict), json_response
            assert "jsonrpc" in json_response, json_response
            assert json_response["jsonrpc"] == "2.0", json_response
            assert "error" in json_response, json_response
            assert json_response["error"] == e.json_rpc_error, e
            error = e.json_rpc_error
            assert isinstance(error, dict), json_response
            assert "data" in error, json_response
            assert "code" in error, json_response
            assert error["code"], json_response
        except Exception as e:
            raise RuntimeError(
                "An unexpected error was raised. Class: {}. Info: "
                "\n{}".format(type(e), pprint.pformat())
            )

    def test_call_invalid_server(self):
        assert_raises(ValueError, emacs_porthole.call, "server_that_cant_exist", "+", 1)

    def test_call_nonexistant_server(self):
        # Make sure this server actually doesn't exist!
        assert_raises(
            emacs_porthole.ServerNotRunningError,
            emacs_porthole.call,
            "nonexistant-server-3280984",
            "+",
            1,
        )


# TODO: Way more tests


class Test__valid_json_rpc_response:
    def test_valid_result(self):
        # Use a value of "None" for the result to try and trip it up. Same for
        # id.
        response = {"jsonrpc": "2.0", "result": None, "id": None}
        assert _valid_json_rpc_response(response)

    def test_string_id(self):
        response = {"jsonrpc": "2.0", "result": None, "id": "sdflkjdjfk"}
        assert _valid_json_rpc_response(response)

    def test_int_id(self):
        response = {"jsonrpc": "2.0", "result": None, "id": 29471507}
        assert _valid_json_rpc_response(response)

    def test_valid_error(self):
        response = {
            "jsonrpc": "2.0",
            "error": {"code": -32600, "message": "some message", "data": None},
            "id": None,
        }
        assert _valid_json_rpc_response(response)

    def test_no_jsonrpc(self):
        response = {"result": "a result", "id": 29471507}
        assert not _valid_json_rpc_response(response)

    def test_no_result_or_error(self):
        response = {"jsonrpc": "2.0", "id": 29471507}
        assert not _valid_json_rpc_response(response)

    def test_no_id(self):
        response = {"jsonrpc": "2.0", "result": "a result"}
        assert not _valid_json_rpc_response(response)


class Test__valid_json_rpc_error:
    def test_valid(self):
        error = {"code": -32600, "message": "some message", "data": None}
        assert emacs_porthole._valid_json_rpc_error(error)

    def test_no_code(self):
        error = {"message": "some message.", "data": None}
        assert not emacs_porthole._valid_json_rpc_error(error)

    def test_no_message(self):
        error = {"code": -32600, "data": None}
        assert not emacs_porthole._valid_json_rpc_error(error)

    def test_no_data(self):
        error = {"code": -32600, "message": "some message."}
        assert not emacs_porthole._valid_json_rpc_error(error)

    def test_not_dict(self):
        error = ["code", "message", "data"]
        assert not emacs_porthole._valid_json_rpc_error(error)
