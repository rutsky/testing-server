import logging

_logger = logging.getLogger(__name__)

__all__ = ('check_solutions',)


async def check_revision(db, revision_id, *, loop):
    curstate = await db.get_revision_state(revision_id)

    _logger.info("Checking revision {} ({!r})".format(revision_id, curstate))

    assert curstate in ('new', 'failed')

    await db.set_revision_state(revision_id, 'checking')

    try:
        user, solution_blob = await db.get_revision_data(revision_id)

        # XXX
        print(user, solution_blob)
    except:
        await db.set_revision_state(revision_id, 'failed')
        raise
    else:
        await db.set_revision_state(revision_id, 'checked')


async def check_solutions(db, assignment_id, *, loop):
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
            await check_revision(db, revision_id, loop=loop)
        except Exception:
            _logger.exception(
                "Check of revision {} failed.".format(revision_id))
