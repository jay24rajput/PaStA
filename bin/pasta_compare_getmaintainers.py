import argparse
import random
import re
import shutil
import subprocess
import tempfile

from collections import defaultdict
from logging import getLogger
from os.path import join
from os import chdir, mkdir
from pathlib import Path

from pypasta import LinuxMailCharacteristics
from pypasta.LinuxMaintainers import load_maintainers, LinuxSubsystem

log = getLogger(__name__[-15:])

linux_directory_skeleton = {"arch",
                          "drivers",
                          "fs",
                          "include",
                          "init",
                          "ipc",
                          "kernel",
                          "lib",
                          "scripts",
                          "Documentation",
                            }

linux_file_skeleton = {"COPYING",
                       "CREDITS",
                       "Kbuild",
                       "Makefile",
                       "README"}


def repo_get_and_write_file(repo, ref, filename, destination):
    content = repo.get_blob(ref, filename)
    with open(join(destination, filename), "wb") as f:
        f.write(content)

def compare_getmaintainers(config, prog, argv):
    parser = argparse.ArgumentParser(prog=prog, description='compare PaStA and official get_maintainer')
    parser.add_argument('--m_id', metavar='m_id', type=str, nargs='+', help="Which message_id\'s to use\n"
                                                                            "Important: see to it that the mailboxes"
                                                                            " affected by the provided id's are "
                                                                            "active in the current Config")
    parser.add_argument('--bulk', metavar='bulk', type=int, help="Bulk-Mode: If no message_id is provided, how many "
                                                          "message_id\'s should be picked randomly and processed")

    parser.add_argument('--notes_path', metavar='notes_path', type=str, help="Where to note erroneous message_id\'s")

    args = parser.parse_args(argv)

    victims = args.m_id
    bulk = args.bulk
    _notes_path = args.notes_path

    def write_messageid_note(message_id, string):
        if _notes_path is not None:
            with open(_notes_path, "a+") as f:
                if message_id not in f.read():
                    f.write('\n' + message_id + " " + string)

    linusTorvaldsTuple = (
        'torvalds@linux-foundation.org', str(LinuxSubsystem.Status.Buried), "THE REST")

    repo = config.repo
    repo.register_mbox(config)

    if victims is None:
        all_message_ids = list(repo.mbox.get_ids(
            time_window=(config.mbox_mindate, config.mbox_maxdate),
            allow_invalid=False))
        all_message_ids = [x for x in all_message_ids if
                           LinuxMailCharacteristics._patches_linux(repo[x])]
        if bulk is None:
            victims = [random.choice(all_message_ids)]
        else:
            victims = random.sample(all_message_ids, bulk)

    tmp = defaultdict(list)
    for victim in victims:
        version = repo.linux_patch_get_version(repo[victim])
        tmp[version].append(victim)
    victims = tmp

    maintainers_version = load_maintainers(config, victims.keys())
    d_tmp = tempfile.mkdtemp()
    try:
        for dir in linux_directory_skeleton:
            mkdir(join(d_tmp, dir))

        for file in linux_file_skeleton:
            Path(join(d_tmp, file)).touch()

        accepted = 0
        declined = 0
        for version, message_ids in victims.items():
            # build the structure anew for every different version
            repo_get_and_write_file(repo, version, "MAINTAINERS", d_tmp)
            repo_get_and_write_file(repo, version, "scripts/get_maintainer.pl", d_tmp)
            linux_maintainers = maintainers_version[version]

            for message_id in message_ids:
                log.info("Processing %s (%s)" % (message_id, version))

                message_raw = repo.mbox.get_raws(message_id)[0]
                f_message = join(d_tmp, 'm')
                with open(f_message, 'wb') as f:
                    f.write(message_raw)

                chdir(d_tmp)

                try:
                    pl_output = subprocess.run(
                        ['perl ' + join(d_tmp, join("scripts", "get_maintainer.pl")) + ' '
                         + f_message
                         + ' --subsystem --status --separator \; --nogit --nogit-fallback --roles --norolestats '
                           '--no-remove-duplicates']
                        , shell=True, check=True
                        , stdout=subprocess.PIPE).stdout.decode("utf-8")
                except subprocess.CalledProcessError as grepexc:
                    log.error("Perl script exited with non-zero exit code %s. Exiting." % grepexc)
                    return

                patch = repo[message_id]
                subsystems = linux_maintainers.get_subsystems_by_files(patch.diff.affected)

                pasta_people = list()
                pasta_lists = set()
                for subsystem in subsystems:
                    lists, maintainers, reviewers = linux_maintainers.get_maintainers(subsystem)
                    subsystem_obj = linux_maintainers[subsystem]
                    subsystem_states = subsystem_obj.status

                    pasta_lists |= lists

                    for reviewer in reviewers:
                        pasta_people.append((reviewer[1].lower(), "reviewer", subsystem[0:40]))

                    for maintainer in maintainers:
                        if len(subsystem_states) != 1:
                            log.error(
                                "maintainer for subsystem %s had more than one status or none? "
                                "Lookup message_id %s" % (subsystem, message_id))
                        elif subsystem_states[0] is LinuxSubsystem.Status.Maintained:
                            status = "maintainer"
                        elif subsystem_states[0] is LinuxSubsystem.Status.Supported:
                            status = "supporter"
                        else:
                            status = str(subsystem_states[0])

                        to_be_appended = (maintainer[1].lower(), status, subsystem[0:40])

                        if to_be_appended != linusTorvaldsTuple:
                            pasta_people.append(to_be_appended)

                log.info("maintainers successfully retrieved by PaStA")

                pl_split = pl_output.split('\n')
                pl_people = pl_split[0].split(';')
                pl_subsystems = set(pl_split[2].split(';'))

                # pl_people will contain lists. Filter them.
                pl_lists = {list.split(' ')[0] for list in pl_people if ' list' in list}
                pl_people = {person for person in pl_people if ' list' not in person}

                # First, check if subsystems actually match. Unfortunatelly,
                # get_maintainers crops subsystem names. Hence, only compare
                # 40 characters of the name
                pasta_subsystems_abbrev = {subsystem[0:40] for subsystem in subsystems}
                pl_subsystems_abbrev = {subsystem[0:40] for subsystem in pl_subsystems}

                isAccepted = True

                missing_subsys_pasta = pl_subsystems_abbrev - pasta_subsystems_abbrev
                missing_subsys_pl = pasta_subsystems_abbrev - pl_subsystems_abbrev
                if len(missing_subsys_pasta):
                    isAccepted = False
                    write_messageid_note(message_id, "Missing Subsystems in PaStA")
                    log.warning('Subsystems: Missing in PaStA: %s' % missing_subsys_pasta)
                if len(missing_subsys_pl):
                    isAccepted = False
                    write_messageid_note(message_id, "Subsystems missin in get_maintainers")
                    log.warning('Subsystems: Missing in get_maintainers: %s' % missing_subsys_pl)
                if pasta_subsystems_abbrev == pl_subsystems_abbrev:
                    log.info('Subsystems: Match')

                # Second, check if list entries match
                missing_lists_pasta = pl_lists - pasta_lists
                missing_lists_pl = pasta_lists - pasta_lists
                if len(missing_lists_pasta):
                    isAccepted = False
                    write_messageid_note(message_id, "Missing List in PaStA")
                    log.warning('Lists: Missing in PaStA: %s' % missing_lists_pasta)
                if len(missing_lists_pl):
                    isAccepted = False
                    write_messageid_note(message_id, "Missing List in get_maintainers")
                    log.warning('Lists: Missing in get_maintainers: %s' % missing_lists_pl)
                if pl_lists == pasta_lists:
                    log.info('Lists: Match')

                # Third, check if maintainers / reviewers / supports match. We now don't care
                # about the subsystem any longer, but we do care about the state of the person
                pl_person_regex = re.compile('.*<(.*)> \((.*):(.*)\)')
                pl_system_regex = re.compile('(.*) \((.*):(.*)\)')
                match = True
                for pl_person in pl_people:
                    match = pl_person_regex.match(pl_person)
                    if not match:
                        write_messageid_note(message_id, "VALUE ERROR")
                        # raise ValueError('regex did not match for person %s from message_id %s'
                        #                 % (pl_person, message_id))
                        match = pl_system_regex.match(pl_person)
                        if not match:
                            raise ValueError('regex did not match for person %s from message_id %s'
                                             % (pl_person, message_id))

                    triple = match.group(1).lower(), match.group(2).lower(), match.group(3)[0:40]

                    if triple in pasta_people:
                        pasta_people.remove(triple)
                    else:
                        isAccepted = False
                        write_messageid_note(message_id, "Missing entry for people in PaStA")
                        log.warning('People: Missing entry for %s (%s, %s)' % triple)
                        match = False

                if len(pasta_people):
                    isAccepted = False
                    write_messageid_note(message_id, "Too much entries in PaStA for people")
                    log.warning('People: Too much entries in PaStA: %s' % pasta_people)
                    match = False

                if match:
                    log.info('People: Match')
                if isAccepted:
                    accepted += 1
                else:
                    declined += 1
        log.info("\nFrom a total of %s message_id\'s:\n%s passed comparison\n%s failed comparison"
                 % (bulk, accepted, declined))


    finally:
        shutil.rmtree(d_tmp)
