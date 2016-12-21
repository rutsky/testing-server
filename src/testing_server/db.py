import logging
import hashlib

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


class TestRuns(Base):
    __tablename__ = 'test_runs'

    id = Column(Integer, primary_key=True)
    revison_id = Column(
        'revision_id', Integer, ForeignKey('revisions.id'), nullable=False)
    # 'running', 'done', 'reported'
    state = Column(String, nullable=False)


class SingleTest(Base):
    __tablename__ = 'single_test'

    id = Column(Integer, primary_key=True)
    test_name = Column(String, nullable=False)
    test_source_id = Column(
        'test_source_id', String, ForeignKey('blobs.id'),
        nullable=False)
    test_common_header_id = Column(
        'test_common_header_id', String, ForeignKey('blobs.id'),
        nullable=False)


class SingleTestPart(Base):
    __tablename__ = 'single_test_part'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    status = Column(Integer, nullable=False)
    info = Column(String)
    log_id = Column(
        'log_id', String, ForeignKey('blobs.id'),
        nullable=True)


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
                solution_id=solution_id, commit_message=msg)
            _logger.debug("Insert SQL statement {}".format(
                stmt))
            await conn.execute(stmt)

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
