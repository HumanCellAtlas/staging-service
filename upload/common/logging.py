import logging
import os
import sys


def get_logger(name):
    ch = logging.StreamHandler(sys.stdout)
    log_level_name = os.environ['LOG_LEVEL'] if 'LOG_LEVEL' in os.environ else 'DEBUG'
    log_level = getattr(logging, log_level_name.upper())
    ch.setLevel(log_level)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s',
                                  datefmt="%Y-%m-%dT%H:%M:%S%z")
    ch.setFormatter(formatter)
    logger = logging.getLogger(name)
    logger.handlers = []
    logger.addHandler(ch)
    logger.setLevel(logging.DEBUG)
    return logger
