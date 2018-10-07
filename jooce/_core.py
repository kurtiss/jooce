from .platform import Platform

__all__ = ["gets", "provides", "invoke"]

platform = Platform()
gets = platform.gets
provides = platform.provides
invoke = platform.invoke
