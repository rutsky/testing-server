import logging
import hashlib
import json

from aiopg.sa import create_engine

import sqlalchemy
from sqlalchemy import Column, Integer, String, LargeBinary, ForeignKey, join
from sqlalchemy.sql.expression import func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import insert

from .abc import AbstractDatabase

__all__ = ('Database',)

_logger = logging.getLogger(__name__)

Base = declarative_base()

_DEBUG_DROP_SCHEMA = False
_DEBUG_CREATE_SCHEMA = False

# TODO
LINKED_PTR_ASSIGNMENT_ID = 1
LINKED_PTR_PATH = "ha3/linked_ptr.hpp"
LINKED_PTR_COMPONENT = "HA#3 linked_ptr"

LAZY_STRING_ASSIGNMENT_ID = 2
LAZY_STRING_PATH = "ha4/lazy_string.hpp"
LAZY_STRING_COMPONENT = "HA#4 lazy_string"

FUNCTION_ASSIGNMENT_ID = 3
FUNCTION_PATH = "ha5/fn.hpp"
FUNCTION_COMPONENT = "HA#5 function"

BIND_ASSIGNMENT_ID = 4
BIND_PATH = "ha6/bind.hpp"
BIND_COMPONENT = "HA#6 bind"

COMPONENT_TO_ASSIGNMENT_ID = {
    LINKED_PTR_COMPONENT: LINKED_PTR_ASSIGNMENT_ID,
    LAZY_STRING_COMPONENT: LAZY_STRING_ASSIGNMENT_ID,
    FUNCTION_COMPONENT: FUNCTION_ASSIGNMENT_ID,
    BIND_COMPONENT: BIND_ASSIGNMENT_ID,
}

PATH_TO_ASSIGNMENT_ID = {
    LINKED_PTR_PATH: LINKED_PTR_ASSIGNMENT_ID,
    LAZY_STRING_PATH: LAZY_STRING_ASSIGNMENT_ID,
    FUNCTION_PATH: FUNCTION_ASSIGNMENT_ID,
    BIND_PATH: BIND_ASSIGNMENT_ID,
}

class Assignments(Base):
    __tablename__ = 'assignments'

    id = Column(Integer, primary_key=True)

    # "linked_ptr"
    name = Column(String, nullable=False)

    # "ha3/linked_ptr.hpp"
    svn_path = Column(String, nullable=False)

    # "HA#3 linked_ptr"
    trac_component = Column(String, nullable=False)


class Tickets(Base):
    __tablename__ = 'tickets'

    # Trac issue ID.
    id = Column(Integer, primary_key=True)

    user = Column(String, nullable=False)

    assignment_id = Column(
        'assignment_id', Integer, ForeignKey('assignments.id'),
        nullable=False)


class Blobs(Base):
    __tablename__ = 'blobs'

    id = Column(String, primary_key=True)
    blob = Column(LargeBinary, nullable=False)


class Revisions(Base):
    __tablename__ = 'revisions'

    # Subversion commit id.
    id = Column(Integer, primary_key=True)

    user = Column(String, nullable=False)
    assignment_id = Column(
        'assignment_id', Integer, ForeignKey('assignments.id'),
        nullable=False)
    solution_id = Column(
        'solution_id', String, ForeignKey('blobs.id'),
        nullable=False)
    commit_message = Column(String, nullable=True)
    # 'obsolete', 'new', 'checking', 'checked', 'failed', 'reported'
    state = Column(String, nullable=False)

    # TODO: store normalized or as JSON field.
    check_result = Column(String, nullable=True)

assignments_tbl = Assignments.__table__
tickets_tbl = Tickets.__table__
revisions_tbl = Revisions.__table__
blobs_tbl = Blobs.__table__


def mock_engine():
    from sqlalchemy import create_engine as ce
    from io import StringIO
    buf = StringIO()

    def dump(sql, *multiparams, **params):
        buf.write(str(sql.compile(dialect=engine.dialect)) + ';')

    engine = ce('postgresql://', echo=True, strategy='mock', executor=dump)
    return buf, engine


def gen_create_sql(metadata):
    buf, engine = mock_engine()
    metadata.create_all(engine)
    return buf.getvalue()


def gen_drop_sql(metadata):
    buf, engine = mock_engine()
    metadata.drop_all(engine)
    return buf.getvalue()


class Database(AbstractDatabase):

    def __init__(self, dsn, *, loop):
        self._dsn = dsn
        self._loop = loop
        self._engine = None

    @property
    def engine(self):
        assert self._engine is not None
        return self._engine

    async def start(self):
        self._engine = await create_engine(self._dsn, loop=self._loop)

        if _DEBUG_DROP_SCHEMA:
            async with self.engine.acquire() as conn:
                sql = gen_drop_sql(Base.metadata)
                await conn.execute(sql)

        if _DEBUG_CREATE_SCHEMA:
            async with self.engine.acquire() as conn:
                sql = gen_create_sql(Base.metadata)
                await conn.execute(sql)

                stmt = assignments_tbl.insert().values(
                    id=LINKED_PTR_ASSIGNMENT_ID,
                    name="linked_ptr",
                    svn_path=LINKED_PTR_PATH,
                    trac_component=LINKED_PTR_COMPONENT,
                )
                await conn.execute(stmt)
                stmt = assignments_tbl.insert().values(
                    id=LAZY_STRING_ASSIGNMENT_ID,
                    name="lazy_string",
                    svn_path=LAZY_STRING_PATH,
                    trac_component=LAZY_STRING_COMPONENT,
                )
                await conn.execute(stmt)
                stmt = assignments_tbl.insert().values(
                    id=FUNCTION_ASSIGNMENT_ID,
                    name="function",
                    svn_path=FUNCTION_PATH,
                    trac_component=FUNCTION_COMPONENT,
                )
                await conn.execute(stmt)
                stmt = assignments_tbl.insert().values(
                    id=BIND_ASSIGNMENT_ID,
                    name="bind",
                    svn_path=BIND_PATH,
                    trac_component=BIND_COMPONENT,
                )
                await conn.execute(stmt)

    async def stop(self):
        self._engine.terminate()
        await self._engine.wait_closed()
        self._engine = None

    async def get_last_synced_svn_revision(self):
        async with self.engine.acquire() as conn:
            stmt = sqlalchemy.select([func.max(revisions_tbl.c.id)])
            _logger.debug("Last revision SQL statement: {}".format(stmt))

            commit_id = await conn.scalar(stmt)
            _logger.debug("Got commit id: {!r}".format(commit_id))

            return commit_id

    async def update_ticket(self, trac_ticket_id, assignment_id, user):
        async with self.engine.acquire() as conn:
            stmt = insert(tickets_tbl).values(
                id=trac_ticket_id,
                user=user,
                assignment_id=assignment_id
            ).on_conflict_do_update(
                index_elements=['id'],
                set_=dict(user=user, assignment_id=assignment_id)
            )

            await conn.execute(stmt)

    async def add_revision(self, id, user, assignment_id, solution_id,
                           msg):
        async with self.engine.acquire() as conn:
            _logger.debug("Inserting revision {!r}".format(
                id, user, assignment_id, solution_id, msg))
            stmt = revisions_tbl.insert().values(
                id=id, user=user, assignment_id=assignment_id,
                solution_id=solution_id, commit_message=msg,
                state='new')
            _logger.debug("Insert SQL statement {}".format(
                stmt))
            await conn.execute(stmt)

    async def reset_revision_checking_state(self):
        stmt = revisions_tbl.update().values(
            state='failed'
        ).where(
            revisions_tbl.c.state == 'checking'
        )
        async with self.engine.acquire() as conn:
            await conn.execute(stmt)

    async def get_revision_state(self, id):
        async with self.engine.acquire() as conn:
            stmt = sqlalchemy.select(
                [revisions_tbl.c.state]
            ).where(
                revisions_tbl.c.id == id
            )
            return await conn.scalar(stmt)

    async def set_revision_state(self, id, state):
        async with self.engine.acquire() as conn:
            stmt = revisions_tbl.update().values(
                state=state
            ).where(
                revisions_tbl.c.id == id
            )
            _logger.debug("Update SQL statement {}".format(stmt))
            await conn.execute(stmt)

    async def get_revision_check_result(self, id):
        async with self.engine.acquire() as conn:
            stmt = sqlalchemy.select(
                [revisions_tbl.c.check_result]
            ).where(
                revisions_tbl.c.id == id
            )
            data = await conn.scalar(stmt)
            if data is not None:
                return json.loads(data)

    async def set_revision_check_result(self, id, check_result):
        async with self.engine.acquire() as conn:
            stmt = revisions_tbl.update().values(
                check_result=json.dumps(check_result)
            ).where(
                revisions_tbl.c.id == id
            )
            _logger.debug("Update SQL statement {}".format(stmt))
            await conn.execute(stmt)

    async def get_revision_user(self, id):
        stmt = sqlalchemy.select(
            [revisions_tbl.c.user]
        ).where(revisions_tbl.c.id == id)

        async with self.engine.acquire() as conn:
            rows = []
            async for row in conn.execute(stmt):
                rows.append(row)

        if rows:
            return rows[0].user
        else:
            return None

    async def get_revision_data(self, id):
        join_stmt = sqlalchemy.join(
            revisions_tbl, blobs_tbl,
            (revisions_tbl.c.solution_id == blobs_tbl.c.id))

        stmt = sqlalchemy.select(
            [revisions_tbl.c.user, blobs_tbl.c.blob]
        ).where(
            revisions_tbl.c.id == id
        ).select_from(
            join_stmt
        )

        async with self.engine.acquire() as conn:
            rows = []
            async for row in conn.execute(stmt):
                rows.append(row)

        assert len(rows) == 1

        return rows[0][0], rows[0][1]

    async def get_blob(self, blob_id):
        stmt = sqlalchemy.select(
            [blobs_tbl.c.blob]
        ).where(blobs_tbl.c.id == blob_id)

        async with self.engine.acquire() as conn:
            rows = []
            async for row in conn.execute(stmt):
                rows.append(row)

            if rows:
                return rows[0].blob
            else:
                return None

    async def store_blob(self, data):
        hash = hashlib.sha256()
        hash.update(data)
        id = hash.hexdigest()

        async with self.engine.acquire() as conn:
            stmt = sqlalchemy.select(
                [func.count(blobs_tbl.c.id)]
            ).where(blobs_tbl.c.id == id)
            found = await conn.scalar(stmt)
            _logger.debug("If blob exists check result: {!r}; SQL: {}".format(
                found, stmt
            ))
            if not found:
                # Still might be inserted in background.
                stmt = insert(blobs_tbl).values(
                    id=id,
                    blob=data,
                ).on_conflict_do_nothing(
                    index_elements=['id']
                )
                await conn.execute(stmt)

        return id

    async def get_user_with_tickets(self, course, assignment):
        async with self.engine.acquire() as conn:
            stmt = sqlalchemy.select(
                [tickets_tbl.c.user]
            ).where(
                (tickets_tbl.c.course == course) &
                (tickets_tbl.c.assignment == assignment)
            )

            users = []
            async for row in conn.execute(stmt):
                users.append(row.user)

        _logger.debug("Users with ticket for course {!r}, assignment {!r}: "
                      "{!r}".format(course, assignment, users))
        return users

    async def get_checkable_solutions(self, assignment_id):
        join_stmt = sqlalchemy.join(
            tickets_tbl, revisions_tbl,
            (tickets_tbl.c.user == revisions_tbl.c.user) &
            (tickets_tbl.c.assignment_id == revisions_tbl.c.assignment_id))

        stmt = sqlalchemy.select(
            [revisions_tbl.c.id, revisions_tbl.c.user,
             revisions_tbl.c.solution_id, revisions_tbl.c.commit_message,
             tickets_tbl.c.id.label('ticket_id'), revisions_tbl.c.state]
        ).select_from(
            join_stmt
        ).where(
            (tickets_tbl.c.assignment_id == assignment_id)
            #&
            #((revisions_tbl.c.state == 'new') |
            # (revisions_tbl.c.state == 'failed'))
        ).order_by(
            revisions_tbl.c.id
        )

        _logger.debug("Getting list of solutions that may be checked. "
                      "SQL: {}".format(stmt))

        async with self.engine.acquire() as conn:
            solutions = []
            async for row in conn.execute(stmt):
                solutions.append(row)

        _logger.debug("Checkable solutions:\n{!r}".format(solutions))

        rev_solutions = []
        users = set()
        for solution in reversed(solutions):
            if solution.user in users:
                # This user has newer solution.
                if solution.state != 'obsolete':
                    await self.set_revision_state(solution.id, 'obsolete')
                continue

            else:
                rev_solutions.append(solution)
                users.add(solution.user)
        solutions = list(reversed(rev_solutions))
        solutions = [s for s in solutions if s.state in ('new', 'failed')]
        solutions.sort(key=lambda x: x.state == 'failed')

        return [solution.id for solution in solutions]

    async def get_reportable_solutions(self, assignment_id):
        join_stmt = sqlalchemy.join(
            tickets_tbl, revisions_tbl,
            (tickets_tbl.c.user == revisions_tbl.c.user) &
            (tickets_tbl.c.assignment_id == revisions_tbl.c.assignment_id))

        stmt = sqlalchemy.select(
            [revisions_tbl.c.id, revisions_tbl.c.user,
             revisions_tbl.c.solution_id, revisions_tbl.c.commit_message,
             tickets_tbl.c.id.label('ticket_id'), revisions_tbl.c.state]
        ).select_from(
            join_stmt
        ).where(
            (tickets_tbl.c.assignment_id == assignment_id) &
            (revisions_tbl.c.state == 'checked')
        ).order_by(
            revisions_tbl.c.id
        )

        _logger.debug("Getting list of solutions which state can be reported. "
                      "SQL: {}".format(stmt))

        async with self.engine.acquire() as conn:
            solutions = []
            async for row in conn.execute(stmt):
                solutions.append(row)

        _logger.debug("Reportable solutions:\n{!r}".format(solutions))

        return [(solution.id, solution.ticket_id) for solution in solutions]
