class GenerationTimeout(Exception):
    pass

class EntityNotFoundError(Exception):
    pass

class GenerationError(Exception):
    pass

class ServerCapacityExceeded(Exception):
    pass

class JobCancelledError(Exception):
    pass

class JobTerminalStateError(Exception):
    pass

