class TestTimedOutException(Exception):
    """Raised when the test times out its overall allowed runtime."""
    pass

class TerminalTestException(Exception):
    """Raised when there is an error in the test which invalidates any retries, test should fail immediately."""
    pass

class JobFailedException(Exception):
    pass

class JobTimedoutException(Exception):
    pass

class PoolResizeFailedException(Exception):
    pass

class NodesFailedToStartException(Exception):
    pass

class StopThreadException(Exception):
    pass