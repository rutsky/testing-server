import os
import logging
import json

import asyncssh

_logger = logging.getLogger(__name__)

__all__ = ('check_solutions',)


async def run_check(user, revision_id, solution_blob, assignment_name,
                    solution_name, tests_dir, common_header,
                    *, ssh_params, loop):
    data_dir = os.path.join('check', assignment_name, user, str(revision_id))

    solution_file = os.path.join(data_dir, solution_name)
    logs_dir = os.path.join(data_dir, 'logs')
    out_log = os.path.join(data_dir, 'out.log')

    async with asyncssh.connect(**ssh_params, loop=loop) as conn:
        await conn.run('mkdir -p {}'.format(data_dir), check=True)
        await conn.run('cat > {}'.format(solution_file),
                       input=solution_blob.decode(),
                       check=True)

        cmd = (
            '/home/cpptest/env/bin/python -u testing.py {solution_file} '
            '--tests-dir {tests_dir} '
            '-p 8 --logs {logs_dir} --common-header {common_header} '
            '--ci-mode | tee -i -a {out_log}'
            ).format(
            solution_file=solution_file, tests_dir=tests_dir,
            logs_dir=logs_dir, out_log=out_log, common_header=common_header)

        process = await conn.create_process(cmd)
        while True:
            line = await process.stdout.readline()

            if not line:
                break

            _logger.debug("{}:{} stdout: {}".format(
                user, revision_id, line.rstrip()))

        await process.wait()

        err = await process.stderr.read()
        parts = err.split('\n')
        idx = parts.index('CI RESULT') + 1
        ci_log = parts[idx]
        assert parts[idx + 1] == 'CI RESULT END'

        ci_data = json.loads(ci_log)

        # XXX
        # import pprint
        # pprint.pprint(ci_data)

        return ci_data


async def check_revision(db, revision_id, *, ssh_params, loop):
    # TODO
    solution_name = 'linked_ptr.hpp'
    tests_dir = 'linked_ptr/tests/'
    common_header = 'linked_ptr/common/common.h'
    assignment_name = 'linked_ptr'

    curstate = await db.get_revision_state(revision_id)

    _logger.info("Checking revision {} ({!r})".format(revision_id, curstate))

    assert curstate in ('new', 'failed')

    await db.set_revision_state(revision_id, 'checking')

    try:
        user, solution_blob = await db.get_revision_data(revision_id)

        # XXX
        # print(user, solution_blob)

        await run_check(user, revision_id, solution_blob, assignment_name,
                        solution_name, tests_dir, common_header,
                        ssh_params=ssh_params, loop=loop)

    except:
        await db.set_revision_state(revision_id, 'failed')
        raise
    else:
        await db.set_revision_state(revision_id, 'checked')


async def check_solutions(db, assignment_id, *,
                          ssh_params,
                          loop):
    _logger.info("Started checking solutions.")

    await db.reset_revision_checking_state()

    while True:
        solutions = await db.get_checkable_solutions(assignment_id)

        if not solutions:
            _logger.info("All available solutions checked.")
            return
        else:
            _logger.info("Need to check {} solutions.".format(solutions))

        revision_id = solutions[0]

        try:
            await check_revision(db, revision_id,
                                 ssh_params=ssh_params, loop=loop)
        except Exception:
            _logger.exception(
                "Check of revision {} failed.".format(revision_id))
