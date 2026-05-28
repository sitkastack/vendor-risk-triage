"""Command-line interface for the vendor risk triage framework.

Provides a single ``vrt`` entry point with six subcommands:

- ``vrt triage`` - run the agent against a submission JSON file
- ``vrt render`` - render an audit pack HTML from a TriageRecord
- ``vrt migrate`` - up-migrate records to a newer output contract
- ``vrt drift`` - check classification drift against the baseline
- ``vrt corpus build`` - build IndexBundles from regulation PDFs
- ``vrt version`` - print framework version and verify pyproject sync

Each subcommand wraps existing framework functionality without
adding new capability. The CLI is a thin tool-shaped layer over the
Python API.

Entry-point compatibility commitment: the ``vrt`` command name and
the subcommand names listed above are part of the framework's public
surface. Renaming or removing a subcommand is a breaking change that
requires a major version bump.

See ``docs/maintenance-workflow.md`` section 1 for the release
procedure and version semantics. See ``cli/dispatcher.py`` for the
argparse wiring; see individual ``cli/cmd_*.py`` modules for each
subcommand's logic.
"""
from cli.dispatcher import main


__all__ = ["main"]
