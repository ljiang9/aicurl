"""Enables `python -m aicurl`."""
import sys

if __package__:
    from .aicurl import main
else:
    from aicurl import main

if __name__ == "__main__":
    sys.exit(main())
