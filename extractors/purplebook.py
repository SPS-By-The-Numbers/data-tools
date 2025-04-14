import argparse
import csv
import logging
import math
import re

from common import common_pdftext_setup

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='Parses a purplebook')

    args = common_pdftext_setup(parser)

    print(args)


if __name__ == '__main__':
    main()
