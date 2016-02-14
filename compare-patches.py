#!/usr/bin/env python3

import sys

from config import *
from PatchEvaluation import preevaluate_single_patch, evaluate_single_patch
from Tools import compare_hashes, getch

commits = sys.argv[1:]

for i in range(len(commits)-1):
    commit_a = commits[i]
    commit_b = commits[i+1]

    compare_hashes(REPO_LOCATION, commit_a, commit_b)

    retval = preevaluate_single_patch(commit_a, commit_b)
    if retval:
        print('Preevaluation: Possible candidates')
        retval = evaluate_single_patch(commit_a, commit_b)
        if retval is None:
            print('Rating: None')
        else:
            _, msg_rating, diff_rating, diff_length_ratio = retval
            print(str(msg_rating) + ' message and ' +
                  str(diff_rating) + ' diff, diff length ratio: ' +
                  str(diff_length_ratio))
    else:
        print('Preevaluation: Not related')
    getch()
