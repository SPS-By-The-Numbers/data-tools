import argparse
import logging

def common_pdftext_setup(parser):
    parser.add_argument('--log-level', default='INFO',
                        help='set log level {DEBUG, INFO, WARNING, ERROR}')
    parser.add_argument('--infile',
                        type=argparse.FileType('r', encoding='UTF-8'),
                        required=True,
                        help='output of "pdf2txt -layout -f start -l end"')
    parser.add_argument('--outfile',
                        type=argparse.FileType('w', encoding='UTF-8'),
                        required=True,
                        help='output csv')
    args = parser.parse_args()
    logging.basicConfig(level=args.log_level)
    return args
