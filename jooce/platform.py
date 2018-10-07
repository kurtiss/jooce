import inspect
import sys

from contextlib import contextmanager
from enum import Enum
from types import ModuleType
from typing import Generic, TypeVar, Union
from weakref import WeakValueDictionary

from dataclasses import dataclass

T = TypeVar('T')


class Scope(Enum):
    platform = None
    batch = "platform"
    item = "batch"

    @property
    def parent(self):
        return type(self)[self.value] if self.value else None


class frozendict:
    def __init__(self, _data=None, _hash=None):
        self._hash = _hash or 0
        self._data = _data or {}

    def updated(self, update):
        result_data = {**self._data, **update}
        result_hash = hash(tuple(result_data.items()))
        return type(self)(_data=result_data, _hash=result_hash)

    def thawed(self):
        return {**self._data}

    def __getitem__(self, key):
        return self._data[key]

    def __hash__(self):
        return self._hash

    def __eq__(self, right):
        if not isinstance(right, type(self)):
            return False
        return self._data == right._data

    def __repr__(self):
        return f"{type(self).__name__}({self._data!r})"

    def get(self, *args, **kwargs):
        return self._data.get(*args, **kwargs)

    def keys(self, *args, **kwargs):
        return self._data.keys(*args, **kwargs)

    def values(self, *args, **kwargs):
        return self._data.values(*args, **kwargs)

    def items(self, *args, **kwargs):
        return self._data.items(*args, **kwargs)


class _TypeMetadataMeta(type(Generic)):
    pass


class TypeMetadata:
    _container_cache = WeakValueDictionary()

    @classmethod
    def _get_container(cls, annotation):
        # https://github.com/python/typing/issues/570
        if getattr(annotation, "__origin__", None) is not Union:
            return None

        for arg in annotation.__args__:
            if hasattr(arg, "__metadata__"):
                return arg

        return None

    @classmethod
    def container_for_arg(cls, owner, argname):
        return cls._get_container(owner.__annotations__[argname])

    @classmethod
    def for_arg(cls, owner, argname):
        return cls.get(owner.__annotations__[argname])

    @classmethod
    def get(cls, annotation):
        container = cls._get_container(annotation)
        if container:
            return container.__metadata__
        return frozendict()

    @classmethod
    def contribute(cls, annotation, metadata):
        in_container = cls._get_container(annotation)

        in_metadata = frozendict() if not in_container else in_container.__metadata__
        out_metadata = in_metadata.updated(metadata)

        try:
            out_container = cls._container_cache[out_metadata]
        except KeyError:
            class out_container(Generic[T], metaclass=_TypeMetadataMeta):
                __metadata__ = out_metadata
            cls._container_cache[out_metadata] = out_container

        return Union[annotation, out_container]

    @classmethod
    def update(cls, owner, argname, metadata):
        owner.__annotations__[argname] = cls.contribute(
            owner.__annotations__[argname],
            metadata
        )


_KEY = "inject.gets"


@dataclass(init=False, frozen=True)
class InjectionKey:
    _handle_code: int = None
    _tag_code: int = None

    def __init__(self, handle, tag=None):
        super().__setattr__("handle", handle)
        super().__setattr__("tag", tag)
        super().__setattr__("_handle_code", id(handle))
        super().__setattr__("_tag_code", id(tag))

    def __repr__(self):
        handle_repr = getattr(self.handle, "__name__", None) or str(self.handle)
        tag_repr = f"/{self.tag}" if self.tag else ""
        return f"::{handle_repr}{tag_repr}"


@dataclass(frozen=True)
class _ReferenceKey:
    _handle_code: int = None
    scope: Scope = None

    def __init__(self, handle, scope=None):
        super().__setattr__("handle", handle)
        super().__setattr__("_handle_code", id(handle))
        super().__setattr__("scope", scope or Scope.platform)

    def __repr__(self):
        return f"{type(self).__name__}(handle={self.handle.__name__!r}, scope={self._scope!r})"


class NotFound(Exception):
    def __init__(self, key):
        self.key = key


class Platform:
    def __init__(self):
        self._scope = Scope.platform
        self._scopes = [Scope.platform]
        self._reference_keys = {}
        self._references = {}
        self._seed(
            InjectionKey(Platform),
            _ReferenceKey(Platform, scope=Scope.platform),
            self
        )

    def _get_scope_instance(self, scope):
        scope_cursor = self._scope
        while scope_cursor:
            if scope_cursor == scope:
                return scope_cursor
        return scope_cursor

    def _seed(self, injection_key, reference_key, reference):
        scope_instance = self._get_scope_instance(reference_key.scope)
        self._reference_keys[injection_key] = reference_key
        self._references.setdefault(scope_instance, {})[reference_key] = reference

    def gets(self, annotation, key=None, tag=None):
        key_cls = key or annotation
        return TypeMetadata.contribute(
            annotation,
            {_KEY: InjectionKey(key_cls, tag)}
        )

    def provides(self, *args, scope=None):
        if len(args) > 2:
            raise NotImplementedError()

        key = None
        handle = None

        if len(args) == 2:
            key_cls = args[0]
            key_tag = args[1]
            key = InjectionKey(key_cls, key_tag)

        if len(args) == 1:
            key = handle = args[0]
            key = InjectionKey(key)

        mapping_decorator = self._mapping_decorator(key, scope)

        if handle:
            mapping_decorator(handle)

        return mapping_decorator

    def _mapping_decorator(self, key, scope):
        def decorator(handle):
            catalog_key = key or InjectionKey(handle)
            self._reference_keys[catalog_key] = _ReferenceKey(handle, scope=scope)
            return handle
        return decorator

    def invoke(self, handle, *args, **kwargs):
        return self.wrap(handle)(*args, **kwargs)

    def wrap(self, handle):
        if callable(handle):
            def wrapper(*in_args, **in_kwargs):
                argspec = inspect.getfullargspec(handle)
                argspec_args = argspec.args

                if inspect.isclass(handle):
                    # ignore 'self'
                    if (argspec_args + [None])[0] == "self":
                        argspec_args = argspec_args[1:]

                args = [None] * len(argspec_args)
                pass_arg_indices = []

                for index, arg in enumerate(argspec_args):
                    arg_annotation = argspec.annotations[arg]
                    arg_key = TypeMetadata.get(arg_annotation).get(_KEY)

                    if not arg_key and isinstance(arg_annotation, type):
                        default_key = InjectionKey(arg_annotation)
                        if default_key in self._reference_keys:
                            arg_key = default_key

                    if arg_key:
                        try:
                            arg_value = self.provide(arg_key)
                        except NotFound:
                            pass_arg_indices.append(index)
                        else:
                            args[index] = arg_value

                in_args = list(in_args)
                missing_args = len(in_args) - len(pass_arg_indices)

                if missing_args > 0:
                    missing_arg_names = [argspec_args[i] for i in pass_arg_indices[:-missing_args]]

                    if missing_args > 1:
                        missing_arg_clauses = [repr(name) for name in missing_arg_names[:-1]]
                        missing_arg_clauses.append(f" and {missing_arg_name[-1]!r}")
                    else:
                        missing_arg_clauses = [repr(name) for name in missing_arg_names]

                    raise TypeError(
                        f"After injection, {handle.__name__}() missing {missing_args} required "
                        f"positional argument{'s' if missing_args > 1 else ''}: "
                        ", ".join(missing_arg_clauses)
                    )

                for index, in_arg in enumerate(in_args):
                    args[pass_arg_indices[index]] = in_arg

                if missing_args < 0:
                    raise TypeError(
                        f"After injection, {handle.__name__}() takes {len(pass_arg_indices)} "
                        f"but {len(in_args)} {'were' if len(in_args) > 1 else 'was'} given"
                    )

                return handle(*args)
            return wrapper

        raise NotImplementedError()

    def provide(self, injection_key):
        try:
            reference_key = self._reference_keys[injection_key]
        except KeyError as exc:
            raise NotFoundError(injection_key) from exc

        scope_instance = self._get_scope_instance(reference_key.scope)

        # provide from cache
        try:
            return self._references[scope_instance][reference_key]
        except KeyError:
            pass

        # or, generate and…
        if callable(reference_key.handle):
            value = self.invoke(reference_key.handle)
        else:
            raise NotImplementedError()

        # add to cache
        scope_instance = self._get_scope_instance(reference_key.scope)
        self._references[scope_instance][reference_key] = value

        return value
