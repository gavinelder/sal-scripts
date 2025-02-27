#!/usr/bin/python


import datetime
import re
import subprocess
import sys
from distutils.version import StrictVersion

sys.path.insert(0, '/usr/local/sal')
import utils


__version__ = '1.0.0'


def main():
    sus_submission = {}
    sus_report = get_sus_install_report()

    sus_submission['facts'] = get_sus_facts()

    # Process managed items and update histories.
    sus_submission['managed_items'] = {}
    sus_submission['update_history'] = []

    for item in sus_report:
        name, version, date = item
        submission_item = {}
        submission_item['date_managed'] = date
        submission_item['status'] = 'PRESENT'
        submission_item['data'] = {'type': 'Apple SUS Install', 'version': version}
        sus_submission['managed_items'][name] = submission_item

    pending = get_pending()
    sus_submission['managed_items'].update(pending)

    utils.set_checkin_results('Apple Software Update', sus_submission)


def get_sus_install_report():
    """Return installed apple updates from softwareupdate"""
    cmd = ['softwareupdate', '--history']
    try:
        output = subprocess.check_output(cmd)
    except subprocess.CalledProcessError:
        # This is a new argument and not supported on all OS versions
        return []

    # Example output:
    # macOS Mojave                                       10.14.1    11/06/2018, 08:41:49
    # macOS 10.14.1 Update                                          11/02/2018, 13:24:17
    # Command Line Tools (macOS High Sierra version 10.13) for Xcode 10.1       11/02/2018, 12:36:15

    # Line one is a "normal" line, name, version, and date are separated
    # by 2+ spaces.
    # Line two has no version number.
    # Line three has such a long name that they decided to output only
    # one space between the name and the version.

    # Drop the header and do an initial split on 2 or more whitespace
    mostly_parsed = [re.split(r' {2,}', l.strip()) for l in output.splitlines()[2:]]
    results = []
    for line in mostly_parsed:
        # If we have three lines, everything is fine.
        if len(line) == 2:
            # Some long update names are displayed without a minimum 2
            # space delimiter, so we have to split them again.
            # This time, we split on a single space and then see if the
            # second item can be cast to a StrictVersion.
            attempt = line[0].rsplit(' ', 1)
            if len(attempt) == 2:
                try:
                    # If we got a StrictVersion, then use our split
                    # results
                    StrictVersion(attempt[1])
                    name = attempt[0]
                    version = attempt[1]
                except ValueError:
                    # Otherwise, there's no versionm, just a name.
                    name = line[0]
                    version = None

            else:
                # I haven't seen examples of this (name with no spaces
                # and a date), but it's here just in case.
                name = line[0]
                version = None
        else:
            name = line[0]
            version = line[1]

        installed = datetime.datetime.strptime(line[-1], '%m/%d/%Y, %H:%M:%S')
        results.append([name, version, installed])

    return results


def get_sus_facts():
    result = {'checkin_module_version': __version__}
    before_dump = datetime.datetime.utcnow()
    cmd = ['softwareupdate', '--dump-state']
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError:
        return result

    with open('/var/log/install.log') as handle:
        install_log = handle.readlines()

    for line in reversed(install_log):
        # TODO: Stop if we go before the subprocess call datetime-wise
        if 'Catalog:' in line and 'catalog' not in result:
            result['catalog'] = line.split()[-1]
        elif 'SUScan: Elapsed scan time = ' in line and 'last_check' not in result:
            # Example date 2019-02-08 10:49:56-05
            # Ahhhh, python 2 stdlib... Doesn't support the %z UTC
            # offset correctly.

            # So split off UTC offset.
            raw_date = ' '.join(line.split()[:2])
            # and make a naive datetime from it.
            naive = datetime.datetime.strptime(raw_date[:-3], '%Y-%m-%d %H:%M:%S')
            # Convert the offset in hours to an int, including the sign.
            offset = int(raw_date[-3:])
            # Invert the offset by subtracting from the naive datetime.
            last_check_datetime = naive - datetime.timedelta(hours=offset)
            # Finally, convert to ISO format and tack a Z on to show
            # we're using UTC time now.
            result['last_check'] = last_check_datetime.isoformat() + 'Z'

        log_time = _get_log_time(line)
        if log_time and before_dump < log_time:
            # Let's not look earlier than when we started
            # softwareupdate.
            break

        elif 'catalog' in result and 'last_check' in result:
            # Once we have both facts, bail; no need to process the
            # entire file.
            break

    return result


def _get_log_time(line):
    try:
        result = datetime.datetime.strptime(line[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        return None
    utc_result = result - datetime.timedelta(hours=int(line[19:22]))
    return utc_result


def get_pending():
    pending_items = {}
    cmd = ['softwareupdate', '-l', '--no-scan']
    try:
        # softwareupdate outputs "No new software available" to stderr,
        # so we pipe it off.
        output = subprocess.check_output(cmd, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        return pending_items

    # Example output

    # Software Update Tool

    # Software Update found the following new or updated software:
    # * macOS High Sierra 10.13.6 Update-
    #       macOS High Sierra 10.13.6 Update ( ), 1931648K [recommended] [restart]
    # * iTunesX-12.8.2
    #       iTunes (12.8.2), 273564K [recommended]

    for line in output.splitlines():
        if line.strip().startswith('*'):
            item = {'date_managed': datetime.datetime.utcnow().isoformat() + 'Z'}
            item['status'] = 'PENDING'
            pending_items[line.strip()[2:]] = item

    return pending_items





if __name__ == "__main__":
    main()
