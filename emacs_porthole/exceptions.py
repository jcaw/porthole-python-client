import requests


class PortholeCallError(RuntimeError):
    """Base class for all errors that might occur during a Porthole call."""


class PortholeConnectionError(PortholeCallError, requests.exceptions.RequestException):
    """Base class for all Porthole connection-related errors."""

    def __init__(self, message, underlying_error=None):
        super(PortholeConnectionError, self).__init__(message)
        self.underlying_error = underlying_error


class ServerNotRunningError(
    PortholeConnectionError, requests.exceptions.ConnectionError
):
    """Error to be raised when the server does not appear to be running."""


class StrangeResponseError(ServerNotRunningError):
    """Error that indicates a strange response was received.

    A strange response is assumed to come from something other than Porthole.
    This implies the Porthole server is not running.

    The original response will be attached to this error, in the `response`
    member.

    """

    def __init__(self, message, response):
        super(StrangeResponseError, self).__init__(message)
        self.response = response
        # TODO: Is this case-sensitive?
        self.response_type = response.headers["Content-Type"]
        self.response_text = response.text


class TimeoutError(PortholeConnectionError, requests.exceptions.Timeout):
    """Error that indicates the request timed out.

    Since Emacs is single-threaded, a timeout may simply mean Emacs is busy.
    Don't assume this means the server is not running.

    """


class HTTPError(PortholeConnectionError):
    # TODO: Should this be a connection error? Should we split out internal 500
    #   errors?
    def __init__(self, message, response):
        super(PortholeConnectionError, self).__init__(message)
        self.response = response
        self.code = response.status_code
        self.content = response.text
        self.content_type = response.headers.get("Content-Type")
