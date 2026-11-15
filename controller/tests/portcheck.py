"""Checking that a class implements a `spotivault.ports` Protocol, signatures included.

    from portcheck import assert_implements
    assert_implements(FakeRecorder, ports.Recorder)

`isinstance` with a runtime-checkable Protocol only checks names. This also checks each method's
parameters (names, kinds, defaults) and that async methods are async, so a real and a fake
implementation can't drift apart. There's no type checker in CI; this is its stand-in for ports.
"""

import inspect
from typing import Any


def protocol_members(protocol: type) -> list[str]:
    """The methods and properties a Protocol declares (not inherited from object or Protocol)."""
    return [
        name
        for name, value in vars(protocol).items()
        if not name.startswith("_") and (callable(value) or isinstance(value, property))
    ]


def assert_implements(cls: type, protocol: type) -> None:
    problems: list[str] = []
    for name in protocol_members(protocol):
        expected = getattr(protocol, name)
        actual = getattr(cls, name, None)
        if actual is None:
            problems.append(f"{name}: missing")
            continue
        if isinstance(expected, property):
            if not isinstance(actual, property):
                problems.append(f"{name}: should be a property")
            continue
        problems += _compare_methods(name, expected, actual)
    if problems:
        raise AssertionError(
            f"{cls.__name__} doesn't implement {protocol.__name__}:\n  " + "\n  ".join(problems)
        )


def _kind(fn: Any) -> str:
    if inspect.isasyncgenfunction(fn):
        return "async generator"
    if inspect.iscoroutinefunction(fn):
        return "async"
    return "plain"


def _compare_methods(name: str, expected: Any, actual: Any) -> list[str]:
    problems = []
    want, got = _kind(expected), _kind(actual)
    # A Protocol declares an async generator as a plain `def ... -> AsyncIterator[...]`, and a
    # context manager as `def ... -> AbstractAsyncContextManager[...]`: accept what returns those.
    returns_iterator = "AsyncIterator" in str(inspect.signature(expected).return_annotation)
    generator_for_iterator = want == "plain" and returns_iterator and got == "async generator"
    if want != got and not generator_for_iterator:
        problems.append(f"{name}: is {got}, should be {want}")
    expected_params = list(inspect.signature(expected).parameters.values())
    actual_params = list(inspect.signature(actual).parameters.values())
    if [_shape(p) for p in expected_params] != [_shape(p) for p in actual_params]:
        problems.append(
            f"{name}: parameters {[_shape(p) for p in actual_params]}, "
            f"should be {[_shape(p) for p in expected_params]}"
        )
    return problems


def _shape(param: inspect.Parameter) -> tuple[str, str, str]:
    default = "" if param.default is inspect.Parameter.empty else repr(param.default)
    return (param.name, param.kind.name, default)
