import json


from emacs_porthole.exceptions import PortholeCallError
from emacs_porthole.utils import is_string


class JsonRpcError(PortholeCallError):
    """Error meaning a JSON-RPC 2.0 error response was returned.

    This means there was an error processing JSON-RPC 2.0 request within Emacs,
    after it was extracted from the HTTP request.

    Members:

    - `raw_response` - the raw JSON-RPC response dictionary. Has three keys,
     "jsonrpc", "error" and "id".

    - `error` - dictionary containing the JSON-RPC error. Has three keys,
      "code", "message" and "data".

    - `code` - The JSON-RPC error code. Type: int

    - `message` - The JSON-RPC error message. Type: str

    - `data` - Any additional data attached to the JSON-RPC error.

    - `elisp_error_type` - If an underlying elisp error was attached to the
      response, this will be a string containing its type.

    - `elisp_error_data` - If an underlying elisp error was attached to the
      response, this will be a list containing its data[1].

    [1]: This should probably be explained in more detail. Elisp errors are
         `cons` cells composed of the error type (in `car`) and a list of data
         (in `cdr`). In most cases the data will be a list with a single item -
         the error's message.

    """

    # TODO: Explain the data structure of this error.
    def __init__(self, response, message=None):
        super(JsonRpcError, self).__init__(
            message or "A JSON-RPC 2.0 Error response was received."
        )
        if not valid_response(response):
            raise ValueError(
                "Response was not a valid JSON-RPC 2.0 response. Please "
                "validate the response before attempting to attach it to "
                "this error."
            )
        self._store_response(response)

    def _store_response(self, response):
        """Deconstruct the response and attach the components to this error.

        """
        # Most important information is the error, but store the whole response
        # just in case the user wants it.
        #
        # We assume the response has already been validated as an error.
        self.raw_response = response
        self.error = response["error"]
        self.code = self.error["code"]
        self.message = self.error["message"]
        self.data = self.error["data"]
        if self.data is not None:
            elisp_error = self.data.get("underlying-error")
        else:
            elisp_error = None
        self.elisp_error_type = elisp_error["type"] if elisp_error else None
        self.elisp_error_data = elisp_error["data"] if elisp_error else None


class ParseError(JsonRpcError):
    """Raised when invalid JSON was sent to the server.

    This error class should normally have an underlying Elisp error attached,
    signifying the problem the JSON decoder encountered.

    """

    def __init__(self, json_rpc_response):
        super(ParseError, self).__init__(
            json_rpc_response, message="The JSON-RPC request was not valid JSON."
        )


class InvalidRequestError(JsonRpcError):
    """Raised when an invalid JSON-RPC 2.0 request was sent to the server.

    This error class should not have an underlying Elisp error attached.

    """

    def __init__(self, json_rpc_response):
        super(InvalidRequestError, self).__init__(
            json_rpc_response, message="Invalid JSON-RPC 2.0 request."
        )


class MethodNotExposedError(JsonRpcError):
    """Raised when the method called was not exposed by the Porthole server.

    This error class won't have an underlying Elisp error attached.

    """

    def __init__(self, json_rpc_response):
        super(MethodNotExposedError, self).__init__(
            json_rpc_response,
            message="This method has not been exposed by the Porthole server.",
        )


class InvalidParamsError(JsonRpcError):
    """Raised when the parameters sent do not match the method's signature.

    As of Porthole Version 0.1.0, paramters are not checked against method
    signatures. You should not encounter this error in practice - an
    `InternalMethodError` will be raised instead.

    """

    def __init__(self, json_rpc_response):
        super(InvalidParamsError, self).__init__(
            json_rpc_response, message="Method cannot be called with these parameters."
        )


class InternalMethodError(JsonRpcError):
    """Raised when there was an error during execution of the method itself.

    This is the error you're most likely to encounter. This means the JSON-RPC
    request itself was fine, but the method called raised an error.

    This error will have the underlying Elisp error attached, and it should be
    inspected for more information. The type can be found in the
    `elisp_error_type` member. The data should normally be available in the
    `elisp_error_data` member.[1]

    [1] There is a small chance this member will be replaced with a string if
        Emacs could not encode the error's data into JSON. In practice, you are
        unlikely to encounter this.

    """

    def __init__(self, json_rpc_response):
        # HACK: Do this early so we can extract info for the error message
        self._store_response(json_rpc_response)
        super(InternalMethodError, self).__init__(
            json_rpc_response,
            message=(
                "There was an error executing the method: `{}`. Data: {}".format(
                    self.elisp_error_type, self.elisp_error_data
                ),
            ),
        )


def raise_error(json_rpc_response):
    """Raise a specific JSON-RPC error, determined by the error code.

    This method assumes you're supplying valid JSON-RPC 2.0, and that it's an
    error. You should validate separately.

    """
    code = json_rpc_response["error"]["code"]
    if code == -32700:
        raise ParseError(json_rpc_response)
    elif code == -32600:
        raise InvalidRequestError(json_rpc_response)
    elif code == -32601:
        raise MethodNotExposedError(json_rpc_response)
    elif code == -32602:
        raise InvalidParamsError(json_rpc_response)
    elif code == -32603:
        raise InternalMethodError(json_rpc_response)
    else:
        raise JsonRpcError(json_rpc_response)


def valid_response_string(string):
    """Check if `string` is a valid JSON-RPC 2.0 response.

    """
    # Sanity check - make sure it's a string input
    #
    # Allow unicode too for Python 2
    if not is_string(string):
        raise ValueError("Input must be a string. Was: {}".format(type(string)))
    try:
        # Decode the response into JSON
        response = json.loads(string)
    except ValueError:
        # Couldn't be decoded. Definitely not valid JSON.
        return False
    return valid_response(response)


def valid_response(response):
    """Check if a decoded JSON object is a valid JSON-RPC 2.0 response."""
    has_id = "id" in response
    id_ = response.get("id")
    valid_id = has_id and (
        # Allow unicode too for Python 2
        is_string(id_)
        or isinstance(id_, int)
        # We also have to account for the server not being able to return an ID
        or id_ is None
    )
    has_result = "result" in response
    valid_error = _valid_error(response.get("error"))
    return (
        isinstance(response, dict)
        # We ensure the version is JSON-RPC 2.0
        and response.get("jsonrpc") == "2.0"
        and valid_id
        and (has_result or valid_error)
    )


def _valid_error(error_part):
    """Is `error_part` a valid error_part from a JSON-RPC 2.0 response object?

    `error_part` should just be the \"error\" member (which should be a
    dictionary). It shouldn't be a full response.

    """
    # We just check that error_part has the right footprint. Don't worry about the
    # specifics. If it has the footpring, it's almost certainly JSON-RPC. We
    # aren't checking the validity of Porthole's encoding mechanisms - just
    # that we did in fact receive a JSON-RPC response.
    return (
        isinstance(error_part, dict)
        and "code" in error_part
        and "message" in error_part
        and "data" in error_part
    )
