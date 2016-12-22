import os
import logging
import textwrap
import pathlib

_logger = logging.getLogger(__name__)


def format_tests(build_url, tests):
    res = textwrap.dedent("""\
    {{{#!th
    test
    }}}
    {{{#!th
    stage
    }}}
    {{{#!th
    result
    }}}
    {{{#!th
    info
    }}}
    {{{#!th
    log
    }}}
    |---
    """)

    results = {
        0: """{{{#!html\n<span style="color: green">SUCCESS</span>\n}}}""",
        1: """{{{#!html\n<span style="color: red">FAILURE</span>\n}}}""",
        2: """{{{#!html\n<span style="color: orange">WARNING</span>\n}}}""",
        3: """{{{#!html\n<span style="color: darkgrey">EXCEPTION</span>\n}}}""",
    }

    at_least_one_failed = False

    for test_file_name, stages, test_source in tests:
        test_file_name = pathlib.Path(test_file_name)
        test_name = test_file_name.name

        successfull_test = all([s[1] == 0 for s in stages])

        if successfull_test:
            continue
        else:
            at_least_one_failed = True

        if not successfull_test:
            res += textwrap.dedent("""\
            {{{{{{#!td rowspan={num_stages}
            {uri}
            }}}}}}
            """).format(
                uri=build_url(test_source, test_name), num_stages=len(stages))
        else:
            res += textwrap.dedent("""\
            {{{{{{#!td rowspan={num_stages}
            {test_name}
            }}}}}}
            """).format(
                test_name=test_name, num_stages=len(stages))

        for stage_name, status, info, log_id in stages:
            log_value = ""
            if log_id and not test_name.startswith('ncomp'):
                log_name = test_file_name.with_suffix('').name + "-" + stage_name + ".log"
                log_value = build_url(log_id, log_name)
            res += textwrap.dedent(
                """\
                {{{{{{#!td
                {stage_name}
                }}}}}}
                {{{{{{#!td
                {result}
                }}}}}}
                {{{{{{#!td
                {info}
                }}}}}}
                {{{{{{#!td
                {log_value}
                }}}}}}
                |---
                """).format(
                stage_name=stage_name, result=results[status], info=info or '',
                log_value=log_value)

    if not at_least_one_failed:
        return ""

    return res


async def report_check_result(db, trac_rpc, revision_id, ticket_id,
                              *, loop):
    # TODO
    #uri = "http://localhost:8080"
    uri = "http://cppcheck.rutsky.org"
    task_name = "linked_ptr"
    common_header_name = "common.h"

    check_result = await db.get_revision_check_result(revision_id)
    user = await db.get_revision_user(revision_id)

    def build_url(blob_id, name):
        return \
            "[{uri}/api/blobs/{blob_id}/{task_name}/{user}/" \
            "{revision}/{name} {name}]".format(
                uri=uri, blob_id=blob_id,
                task_name=task_name, user=user, revision=revision_id,
                name=name)

    res = ""

    res += "Tested revision {} by {}.\n\n".format(revision_id, user)

    smoke_test_res = format_tests(build_url, check_result['smoke_tests']['tests'])
    if smoke_test_res:
        res += textwrap.dedent(
            """\
            == Smoke tests ==

            """)
        res += smoke_test_res

    smoke_tests_exit_code = check_result['smoke_tests']['exit_code']

    if smoke_tests_exit_code == 0:
        main_tests_res = format_tests(build_url, check_result['tests']['tests'])
        if main_tests_res:
            res += textwrap.dedent(
                """\
                == Main tests ==

                """)
            res += main_tests_res

    success = False
    if smoke_tests_exit_code == 0 and check_result['tests']['exit_code'] == 0:
        res += "\nAll tests passed. Good job!\n\n"
        success = True
    else:
        res += "\nCommon header used in some tests: " + build_url(
            check_result['common_header_contents'],
            common_header_name) + "\n\n"

    attributes = {}
    if not success:
        attributes = {
            'type': 'ожидаются исправления'
        }
    await trac_rpc.ticket.update(ticket_id, res, attributes, True)

    #import pprint
    #pprint.pprint(check_result)

    #with open('log.txt', 'a') as f:
    #    f.write(res)


async def report_solutions(db, trac_rpc, assignment_id,
                           *, loop):
    _logger.info("Started reporting results.")

    while True:
        solutions = await db.get_reportable_solutions(assignment_id)

        if not solutions:
            _logger.info("All checked solutions reported.")
            return
        else:
            _logger.info("Need to report {} solutions.".format(solutions))

        for solution in solutions:
            revision_id, ticket_id = solution

            try:
                await report_check_result(db, trac_rpc, revision_id, ticket_id,
                                          loop=loop)

                await db.set_revision_state(revision_id, 'reported')

            except Exception:
                _logger.exception(
                    "Report of revision {} to ticket {} failed.".format(
                        revision_id, ticket_id))
