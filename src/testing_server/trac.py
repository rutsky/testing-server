import logging

_logger = logging.getLogger(__name__)


async def sync_ticket(db, trac_rpc, ticket_id, component_to_assignment):
    attributes = (await trac_rpc.ticket.get(ticket_id))[3]

    component = attributes['component']

    if component not in component_to_assignment:
        return False

    course, assignment = component_to_assignment[component]
    user = attributes['reporter']

    _logger.debug("Syncing {!r}".format((course, user, assignment, ticket_id)))

    await db.create_ticket_if_doesnt_exists(
        course, user, assignment, ticket_id)

    return True

async def sync_tickets(db, trac_rpc, component_to_assignment):
    try:
        _logger.info("Tickets sync started")

        api_version = await trac_rpc.system.getAPIVersion()
        _logger.info("API version: {!r}".format(api_version))

        tickets_ids = await trac_rpc.ticket.query("max=0")
        _logger.info("Trac has {} tickets".format(len(tickets_ids)))

        for ticket_id in tickets_ids:
            await sync_ticket(db, trac_rpc, ticket_id, component_to_assignment)

    finally:
        _logger.info("Tickets sync finished")
