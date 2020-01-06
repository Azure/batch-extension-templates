import logger
import traceback


class TestTimedOutException(Exception):
    """Raised when the test times out its overall allowed runtime."""
    pass


class TerminalTestException(Exception):
    """Raised when there is an error in the test which invalidates any retries, test should fail immediately."""
    pass


class StopThreadException(Exception):
    """Raised by the main thread when we want the sub-thread running the test to cleanup and shutdown."""
    pass


class NonTerminalException(Exception):
    """Base class for non-terminal exceptions, define standard logging behaviour here."""

    def __init__(self, identifier, message):
        logger.warning("NonTerminalException thrown for id: [{}]. Exception: {} - '{}'. StackTrace '{}'."
                       .format(identifier, self.__class__.__name__, message,  traceback.print_exc()))


class JobFailedException(NonTerminalException):

    def __init__(self, identifier, message):
        super().__init__(identifier, message)


class JobTimedoutException(NonTerminalException):

    def __init__(self, identifier, message):
        super().__init__(identifier, message)


class PoolResizeFailedException(NonTerminalException):

    def __init__(self, identifier, message):
        super().__init__(identifier, message)


class NodesFailedToStartException(NonTerminalException):

    def __init__(self, identifier, message):
        super().__init__(identifier, message)


class JobAlreadyCompleteException(NonTerminalException):
    """Raised when we timeout waiting for idle nodes and we try retarget the job to a new pool, but hit the race 
    condition where the nodes have since gone idle and the job already completed."""

    def __init__(self, identifier, message):
        super().__init__(identifier, message)
