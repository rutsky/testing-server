import asyncio
import logging
from xml.dom import minidom

import yarl

_logger = logging.getLogger(__name__)


def parse_log_entry(logentry, path_to_assignment_id):
    revision = int(logentry.attributes['revision'].value)

    _logger.debug("Parsing revision {}".format(revision))

    author = logentry.getElementsByTagName(
        'author')[0].childNodes[0].wholeText
    msg_nodes = logentry.getElementsByTagName('msg')[0].childNodes
    msg = msg_nodes[0].wholeText if msg_nodes else None

    for path in logentry.getElementsByTagName('path'):
        action = path.attributes['action'].value
        file = path.childNodes[0].wholeText

        if action == 'D':
            continue

        user, _, file_path = file.lstrip('/').partition('/')

        if not file_path:
            continue

        if user != author:
            _logger.warning(
                "In commit {} path {!r} doesn't correspond to "
                "commit author {!r}.".format(revision, file, author))
            continue

        if file_path in path_to_assignment_id:
            yield revision, file, author, msg, \
                  path_to_assignment_id[file_path]


def parse_log_xml(revs_xml, path_to_assignment_id):
    xmldoc = minidom.parseString(revs_xml)
    for logentry in xmldoc.getElementsByTagName('logentry'):
        try:
            yield from parse_log_entry(logentry, path_to_assignment_id)

        except Exception:
            _logger.exception("Failed to parse Subversion XML log entry: "
                              "{}".format(logentry.toxml()))
            raise


async def check_output(*args, loop, args_to_print=None):
    args_to_print = args_to_print if args_to_print is not None else args
    _logger.debug("Running {!r}".format(args_to_print))

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        loop=loop,
    )
    out, err = await proc.communicate()

    exitcode = proc.returncode
    if exitcode != 0:
        raise RuntimeError(
            "Command {!r} returned exit code {}. "
            "Stderr:\n{}".format(
                args_to_print, exitcode, err,
            ))

    if err:
        _logger.error("Command {!r} returned something in "
                      "stderr:\n{}".format(args_to_print, err))

    return out


def _obfuscate_password(args):
    return ["********" if "password" in arg else arg for arg in args]


async def svn_log(svn_uri, *,
                  last_commit_id=None,
                  svn_username=None, svn_password=None, loop):
    cmd = ['svn', 'log', '--no-auth-cache', '--xml', '-v']
    if svn_username is not None:
        cmd.append('--username={}'.format(svn_username))
    cmd.append('-r{}:HEAD'.format(last_commit_id or 0))
    if svn_password is not None:
        cmd.append('--password={}'.format(svn_password))

    cmd.append(svn_uri)

    revs_xml = await check_output(*cmd, loop=loop,
                                  args_to_print=_obfuscate_password(cmd))

    return revs_xml


async def svn_checkout(revision, file, svn_uri, svn_username=None, svn_password=None,
                       *, loop):
    cmd = ['svn', 'cat', '--no-auth-cache']
    if svn_username is not None:
        cmd.append('--username={}'.format(svn_username))
    if svn_password is not None:
        cmd.append('--password={}'.format(svn_password))

    cmd.append(str(yarl.URL(svn_uri) / file.lstrip('/')) + '@' + str(revision))

    file_contents = await check_output(*cmd, loop=loop,
                                       args_to_print=_obfuscate_password(cmd))

    return file_contents


async def sync_svn(db,
                   path_to_assignment_id,
                   svn_uri,
                   *, svn_username=None, svn_password=None, loop):
    last_commit_id = await db.get_last_synced_svn_revision()

    _logger.info("Retrieving subversion log starting from {} commit".format(
        str(last_commit_id)
    ))

    revs_xml = await svn_log(
        svn_uri,
        last_commit_id=last_commit_id,
        svn_username=svn_username, svn_password=svn_password, loop=loop)

    for revision, file, author, msg, assignment_id in parse_log_xml(
            revs_xml, path_to_assignment_id):
        if revision <= (last_commit_id or 0):
            continue

        _logger.info(
            "Fetching solution for {} commit by {}: {}".format(
                revision, author, file
            ))
        solution_data = await svn_checkout(
            revision, file, svn_uri, svn_username, svn_password, loop=loop)

        solution_id = await db.store_blob(solution_data)

        await db.add_revision(revision, author, assignment_id, solution_id,
                              msg)

    _logger.info("Done syncing Subversion")
