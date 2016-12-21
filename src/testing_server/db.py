from aiopg.sa import create_engine
from sqlalchemy import Column, Integer, String, LargeBinary, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import insert

from .abc import AbstractDatabase

__all__ = ('Database',)


Base = declarative_base()

_DEBUG_DROP_SCHEMA = False
_DEBUG_CREATE_SCHEMA = False


class Tickets(Base):
    __tablename__ = 'tickets'

    id = Column(Integer, primary_key=True)
    course = Column(String, nullable=False)
    user = Column(String, nullable=False)
    assignment = Column(String, nullable=False)


class Solutions(Base):
    __tablename__ = 'solutions'

    id = Column(Integer, primary_key=True)
    ticket_id = Column(
        'ticket_id', Integer, ForeignKey('tickets.id'), nullable=False)
    revision = Column(Integer, nullable=False)


class Blobs(Base):
    __tablename__ = 'blobs'

    id = Column(String, primary_key=True)
    blob = Column(LargeBinary, nullable=False)


class TestRuns(Base):
    __tablename__ = 'test_runs'

    id = Column(Integer, primary_key=True)
    solution_id = Column(
        'solution_id', Integer, ForeignKey('solutions.id'), nullable=False)
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
                async with conn.cursor() as cur:
                    sql = gen_drop_sql(Base.metadata)
                    await cur.execute(sql)

        if _DEBUG_CREATE_SCHEMA:
            async with self.engine.acquire() as conn:
                async with conn.cursor() as cur:
                    sql = gen_create_sql(Base.metadata)
                    await cur.execute(sql)

    async def stop(self):
        self._engine.terminate()
        await self._engine.wait_closed()
        self._engine = None

    async def create_ticket_if_doesnt_exists(
            self, course, user, assignment, trac_ticket_id):
        async with self.engine.acquire() as conn:
            print(course, user, assignment, trac_ticket_id)

            stmt = insert(Tickets.__table__).values(
                id=trac_ticket_id,
                course=course,
                user=user,
                assignment=assignment
            ).on_conflict_do_nothing(index_elements=['id'])

            await conn.execute(stmt)
