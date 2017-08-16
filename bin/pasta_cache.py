#!/usr/bin/env python3

"""
PaStA - Patch Stack Analysis

Copyright (c) OTH Regensburg, 2016-2017

Author:
  Ralf Ramsauer <ralf.ramsauer@oth-regensburg.de>

This work is licensed under the terms of the GNU GPL, version 2.  See
the COPYING file in the top-level directory.
"""

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__),
                                                '..')))
from PaStA import *


def parse_choices(choices):
    stack = upstream = mbox = False

    if choices:
        if choices == 'mbox':
            mbox = True
        elif choices == 'stack':
            stack = True
        elif choices == 'upstream':
            upstream = True
        else:
            mbox = stack = upstream = True

    return stack, upstream, mbox


def remove_if_exist(filename):
    if os.path.isfile(filename):
        os.remove(filename)


def cache(config, prog, argv):
    parser = argparse.ArgumentParser(prog=prog,
                                     description='create commit cache')

    choices = ['mbox', 'stack', 'upstream', 'all']
    parser.add_argument('-create', metavar='create', default=None,
                        choices=choices,
                        help='create cache for commits on patch stacks, '
                             'upstream commits, mailbox or all')
    parser.add_argument('-clear', metavar='clear', default=None, choices=choices)

    parser.add_argument('-mindate', dest='mindate', metavar='mindate',
                        default=config.mbox_mindate, type=parse_date_ymd,
                        help='Skip mails older than mindate '
                             '(only together with -create mbox, '
                             'default: %(default)s)')
    parser.add_argument('-maxdate', dest='maxdate', metavar='maxdate',
                        default=config.mbox_maxdate, type=parse_date_ymd,
                        help='Skip mails older than mindate '
                             '(only together with -create mbox, '
                             'default: %(default)s)')

    args = parser.parse_args(argv)

    psd = config.psd
    repo = config.repo

    create_stack, create_upstream, create_mbox = parse_choices(args.create)
    clear_stack, clear_upstream, clear_mbox = parse_choices(args.clear)

    if clear_stack:
        remove_if_exist(config.f_ccache_stack)
    if clear_upstream:
        remove_if_exist(config.f_ccache_upstream)
    if clear_mbox:
        remove_if_exist(config.f_ccache_mbox)

    if create_stack:
        repo.load_ccache(config.f_ccache_stack)
        repo.cache_commits(psd.commits_on_stacks)
        repo.export_ccache(config.f_ccache_stack)
        repo.clear_commit_cache()
    if create_upstream:
        repo.load_ccache(config.f_ccache_upstream)
        repo.cache_commits(psd.upstream_hashes)
        repo.export_ccache(config.f_ccache_upstream)
        repo.clear_commit_cache()
    if create_mbox:
        # load existing cache
        repo.load_ccache(config.f_ccache_mbox)

        # get overall mail index
        index = mbox_load_index(config.f_mailbox_index)

        # filter dates
        index = [key for (key, value) in index.items()
                 if value[0] >= args.mindate and value[0] <= args.maxdate]

        # yay, we can treat emails just like ordinary commit hashes
        repo.cache_commits(index)

        repo.export_ccache(config.f_ccache_mbox)
        repo.clear_commit_cache()


if __name__ == '__main__':
    config = Config(sys.argv[1])
    cache(config, sys.argv[0], sys.argv[2:])
