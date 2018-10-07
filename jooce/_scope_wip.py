from asyncio import create_task, Task
from functools import wraps

try:
    from contextvars import ContextVar
except ImportError:
    from aiocontextvars import ContextVar


class Scope:
    __parent__ = None

    def __init__(self, parent):
        self._data = {}
        self._parent = parent

    @property
    def parent(self):
        return self._parent

    def transition(self, scope_cls):
        if not isinstance(self, scope_cls.__parent__):
            raise ValueError("Invalid transition")
        return scope_cls(self)

    def getitem(self, key):
        try:
            return self._data[key]
        except KeyError:
            if self.parent is None:
                raise
        return self.parent.getitem(key)

    def setitem(self, key, value, scope=None):
        scope_cls = scope or type(self)
        if isinstance(self, scope):
            self._data[key] = value
            return
        if self.parent is None:
            raise ValueError(f"No {scope_cls.__name__!r} has been engaged.")
        return self.parent.setitem(key, value, scope=scope_cls)


class GlobalScope(Scope):
    pass


class SessionScope(Scope):
    __parent__ = GlobalScope


class RequestScope(Scope):
    __parent__ = SessionScope


class JobScope(Scope):
    __parent__ = RequestScope


class Scopes:
    global = GlobalScope
    session = SessionScope
    request = RequestScope
    job = JobScope


scope_var = ContextVar('scope_var')
scope_var.set(GlobalScope())


async def transition(scope_cls, callback, **transition_context):
    async def enter_one(next_scope_cls, scopes):
        current_scope = scope_var.get()
        next_scope = current_scope.transition(next_scope_cls, **transition_context)
        scope_var.set(next_scope)
        return await enter_all(scopes)

    async def enter_all(scopes):
        try:
            scope_cls = scopes.pop()
        except IndexError:
            return await callback
        return await create_task(enter_one(scope_cls, scopes))

    current_scope = scope_var.get()
    scopes = []
    scope_cursor = scope_cls
    if isinstance(current_scope, scope_cursor):
        raise ValueError("Already in scope {scope_cursor.__name__!r}")

    while not isinstance(current_scope, scope_cursor):
        scopes.append(scope_cursor)
        scope_cursor = scope_cursor.__parent__
        if scope_cursor is None:
            scopes_to_enter = None
            break

    if scopes_to_enter is None:
        raise ValueError(
            f"No path to transition from scope {type(current_scope).__name__!r} "
            f"to {scope_cls.__name__!r}."
        )

    await enter_all(scopes_to_enter)


def transitions(scope_cls, **transition_context):
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            async def callback():
                return await func(*args, **kwargs)
            await transition(scope_cls, callback(), **transition_context)
        return wrapper
    return decorator
