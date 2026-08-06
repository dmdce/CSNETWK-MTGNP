import argparse
import logging
import sys

def setup_logging(verbose: bool = False):
    """
    name: setup_logging
    description: Configures the root logger with a console handler.
                 If verbose is True, set level to DEBUG; otherwise set to WARNING.
                 Log types: DEBUG, INFO, WARNING, ERROR
    """

    # Set up formatter
    formatter = logging.Formatter(fmt='%(asctime)s - %(filename)s - %(message)s',
                                  datefmt='%Y-%m-%d %H:%M:%S')

    # Console handler w/ formatter
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    # Root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(console_handler)
    root_logger.setLevel(logging.DEBUG if verbose else logging.WARNING)

def get_logger(name: str = None) -> logging.Logger:
    """
    name: get_logger
    description: Convenience function to get a named logger. If no name, returns the root logger.
    """

    return logging.getLogger(name)