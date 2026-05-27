"""Allow ``python -m cli`` invocation of the dispatcher.

The ``vrt`` console script (registered via ``pyproject.toml``) is the
primary entry point. This module exists so ``python -m cli`` also
works, which is useful for development environments where the
console script is not yet installed.

Coverage note: this module runs only as a subprocess (`python -m cli`).
Coverage tooling under pytest does not measure subprocess execution
without explicit setup, so the body is marked no-cover. The
subprocess test in test_cli_dispatcher.py verifies the path works
end-to-end.
"""
import sys  # pragma: no cover

from cli.dispatcher import main  # pragma: no cover


sys.exit(main())  # pragma: no cover
