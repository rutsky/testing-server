import asyncio
import os
import logging
import json
import codecs

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

        async def log_stream(stream, name):
            while True:
                try:
                    line = await stream.readline()
                except asyncio.CancelledError:
                    _logger.debug("{}:{} {}: cancelling reading".format(
                        user, revision_id, name))
                    return

                if not line:
                    _logger.debug("{}:{} {}: got end of stream".format(
                        user, revision_id, name))
                    break

                _logger.debug("{}:{} {}: {}".format(
                    user, revision_id, name, line.rstrip()))

        process = await conn.create_process(cmd)
        stdout_logger_task = loop.create_task(
            log_stream(process.stdout, "stdout"))

        try:
            _logger.debug("{}:{} waiting process termination...".format(
                user, revision_id))
            await process.wait()
        except Exception:
            stdout_logger_task.cancel()
            raise

        _logger.debug("{}:{} reading stderr...".format(
            user, revision_id))
        err = await process.stderr.read()
        _logger.debug("{}:{} got {} bytes in stderr".format(
            user, revision_id, len(err)))

        try:
            parts = err.split('\n')
            idx = parts.index('CI RESULT') + 1
            ci_log = parts[idx]
            assert parts[idx + 1] == 'CI RESULT END'
        except:
            _logger.exception(
                "{}:{} stderr parsing failed:\n"
                "----- BEGIN -----\n{}\n----- END -----\n".format(
                    user, revision_id, err))
            raise

        ci_data = json.loads(ci_log)

        #import pprint
        #pprint.pprint(ci_data)

        return ci_data


async def check_revision(db, revision_id, *, ssh_params, loop):
    # TODO
    solution_name = 'lazy_string.hpp'
    tests_dir = 'lazy_string/tests/'
    common_header = 'lazy_string/tests/common.h'
    assignment_name = 'lazy_string'

    curstate = await db.get_revision_state(revision_id)

    _logger.info("Checking revision {} ({!r})".format(revision_id, curstate))

    assert curstate in ('new', 'failed')

    await db.set_revision_state(revision_id, 'checking')

    try:
        user, solution_blob = await db.get_revision_data(revision_id)

        ci_data = await run_check(
            user, revision_id, solution_blob, assignment_name,
            solution_name, tests_dir, common_header,
            ssh_params=ssh_params, loop=loop)

        async def decode(base64_field):
            if not base64_field:
                return None
            return await db.store_blob(
                codecs.decode(base64_field.encode(), 'base64'))

        ci_data['common_header_contents'] = await decode(
            ci_data['common_header_contents'])

        for test in ci_data['smoke_tests']['tests']:
            for test_part in test[1]:
                test_part[3] = await decode(test_part[3])
            test[2] = await decode(test[2])
        for test in ci_data['tests']['tests']:
            for test_part in test[1]:
                test_part[3] = await decode(test_part[3])
            test[2] = await decode(test[2])

        prev_ci_data = await db.get_revision_check_result(revision_id)

        await db.set_revision_check_result(revision_id, ci_data)

        def get_failed_tests_from_tests(tests):
            for test_file_name, stages, test_source in tests:
                if not all([s[1] == 0 for s in stages]):
                    yield (test_file_name, stages, test_source)

        def get_failed_tests_from_check_result(check_result):
            smoke_tests_exit_code = check_result['smoke_tests']['exit_code']
            if smoke_tests_exit_code != 0:
                yield from get_failed_tests_from_tests(
                    check_result['smoke_tests']['tests'])
            else:
                yield from get_failed_tests_from_tests(
                    check_result['tests']['tests'])

        prev_failures = None
        if prev_ci_data:
            prev_failures = list(
                get_failed_tests_from_check_result(prev_ci_data))
            _logger.info(
                "revision {}: in previous check {} errors".format(
                    revision_id, len(prev_failures)))
        cur_failures = list(get_failed_tests_from_check_result(ci_data))
        _logger.info(
            "revision {}: in current check {} errors".format(
                revision_id, len(cur_failures)))

        if prev_failures == cur_failures:
            # No new failure since last check.
            _logger.info(
                "revision {}: no new failures since last check for".format(
                    revision_id))
            await db.set_revision_state(revision_id, 'reported')
        else:
            await db.set_revision_state(revision_id, 'checked')

    except:
        await db.set_revision_state(revision_id, 'failed')
        raise


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
