# coding=utf-8
# We often have one-arg-per column, so these checks aren't so useful.
# pylint: disable=too-many-arguments,too-many-public-methods
"""
Lower-level database access.
"""
from __future__ import absolute_import

import datetime
import json
import logging
from functools import reduce as reduce_
from itertools import chain

import numpy
from sqlalchemy import create_engine, select, text, bindparam, exists, and_, or_, Index, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine.url import URL as EngineUrl
from sqlalchemy.exc import IntegrityError

from datacube.config import LocalConfig
from datacube.index.fields import OrExpression
from datacube.index.postgres.tables._core import schema_qualified
from datacube.index.postgres.tables._dataset import DATASET_LOCATION, METADATA_TYPE
from . import tables
from ._fields import parse_fields, NativeField
from .tables import DATASET, DATASET_SOURCE, STORAGE_TYPE, STORAGE_UNIT, DATASET_STORAGE, COLLECTION

DATASET_URI_FIELD = DATASET_LOCATION.c.uri_scheme + ':' + DATASET_LOCATION.c.uri_body
_DATASET_SELECT_FIELDS = (
    DATASET,
    # The most recent file uri. We may want more advanced path selection in the future...
    select([
        DATASET_URI_FIELD
    ]).where(
        and_(
            DATASET_LOCATION.c.dataset_ref == DATASET.c.id,
            DATASET_LOCATION.c.uri_scheme == 'file'
        )
    ).order_by(
        DATASET_LOCATION.c.added.desc()
    ).limit(1).label('local_uri')
)

PGCODE_UNIQUE_CONSTRAINT = '23505'

_LOG = logging.getLogger(__name__)


def _split_uri(uri):
    """
    Split the scheme and the remainder of the URI.

    >>> _split_uri('http://test.com/something.txt')
    ('http', '//test.com/something.txt')
    >>> _split_uri('eods:LS7_ETM_SYS_P31_GALPGS01-002_101_065_20160127')
    ('eods', 'LS7_ETM_SYS_P31_GALPGS01-002_101_065_20160127')
    >>> _split_uri('file://rhe-test-dev.prod.lan/data/fromASA/LANDSAT-7.89274.S4A2C1D3R3')
    ('file', '//rhe-test-dev.prod.lan/data/fromASA/LANDSAT-7.89274.S4A2C1D3R3')
    """
    comp = uri.split(':')
    scheme = comp[0]
    body = ':'.join(comp[1:])
    return scheme, body


class PostgresDb(object):
    """
    A very thin database access api.

    It exists so that higher level modules are not tied to SQLAlchemy, connections or specifics of database-access.

    (and can be unit tested without any actual databases)
    """

    def __init__(self, engine, connection):
        self._engine = engine
        self._connection = connection

    @classmethod
    def connect(cls, hostname, database, username=None, password=None, port=None):
        _engine = create_engine(
            EngineUrl(
                'postgresql',
                host=hostname, database=database, port=port,
                username=username, password=password,
            ),
            echo=False,
            # 'AUTOCOMMIT' here means READ-COMMITTED isolation level with autocommit on.
            # When a transaction is needed we will do an explicit begin/commit.
            isolation_level='AUTOCOMMIT',

            json_serializer=_to_json,
            # json_deserializer=my_deserialize_fn
        )
        _connection = _engine.connect()
        return PostgresDb(_engine, _connection)

    @classmethod
    def from_config(cls, config=LocalConfig.find()):
        return PostgresDb.connect(
            config.db_hostname,
            config.db_database,
            config.db_username,
            config.db_password,
            config.db_port
        )

    def init(self):
        """
        Init a new database (if not already set up).

        :return: If it was newly created.
        """
        return tables.ensure_db(self._connection, self._engine)

    def begin(self):
        """
        Start a transaction.

        Returns a transaction object. Call commit() or rollback() to complete the
        transaction or use a context manager:

            with db.begin() as transaction:
                db.insert_dataset(...)

        :return: Tranasction object
        """
        return _BegunTransaction(self._connection)

    def insert_dataset(self, metadata_doc, dataset_id, collection_id=None):
        """
        Insert dataset if not already indexed.
        :type metadata_doc: dict
        :type dataset_id: str or uuid.UUID
        :type collection_id: int
        :return: whether it was inserted
        :rtype: bool
        """
        if collection_id is None:
            collection_result = self.get_collection_for_doc(metadata_doc)
            if not collection_result:
                _LOG.debug('Attempted failed match on doc %r', metadata_doc)
                raise RuntimeError('No collection matches dataset')
            collection_id = collection_result['id']
            _LOG.debug('Matched collection %r', collection_id)
        else:
            _LOG.debug('Using provided collection %r', collection_id)

        try:
            collection_ref = bindparam('collection_ref')
            ret = self._connection.execute(
                # Insert if not exists.
                #     (there's still a tiny chance of a race condition: It will throw an integrity error if another
                #      connection inserts the same dataset in the time between the subquery and the main query.
                #      This is ok for our purposes.)
                DATASET.insert().from_select(
                    ['id', 'collection_ref', 'metadata_type_ref', 'metadata'],
                    select([
                        bindparam('id'), collection_ref,
                        select([
                            COLLECTION.c.metadata_type_ref
                        ]).where(
                            COLLECTION.c.id == collection_ref
                        ).label('metadata_type_ref'),
                        bindparam('metadata', type_=JSONB)
                    ]).where(~exists(select([DATASET.c.id]).where(DATASET.c.id == bindparam('id'))))
                ),
                id=dataset_id,
                collection_ref=collection_id,
                metadata=metadata_doc
            )
            return ret.rowcount > 0
        except IntegrityError as e:
            if e.orig.pgcode == PGCODE_UNIQUE_CONSTRAINT:
                _LOG.info('Duplicate dataset, not inserting: %s', dataset_id)
                # We're still going to raise it, because the transaction will have been invalidated.
            raise

    def ensure_dataset_location(self, dataset_id, uri):
        """
        Add a location to a dataset if it is not already recorded.
        :type dataset_id: str or uuid.UUID
        :type uri: str
        """
        scheme, body = _split_uri(uri)
        # Insert if not exists.
        #     (there's still a tiny chance of a race condition: It will throw an integrity error if another
        #      connection inserts the same location in the time between the subquery and the main query.
        #      This is ok for our purposes.)
        self._connection.execute(
            DATASET_LOCATION.insert().from_select(
                ['dataset_ref', 'uri_scheme', 'uri_body'],
                select([
                    bindparam('dataset_ref'), bindparam('uri_scheme'), bindparam('uri_body'),
                ]).where(
                    ~exists(select([DATASET_LOCATION.c.id]).where(
                        and_(
                            DATASET_LOCATION.c.dataset_ref == bindparam('dataset_ref'),
                            DATASET_LOCATION.c.uri_scheme == bindparam('uri_scheme'),
                            DATASET_LOCATION.c.uri_body == bindparam('uri_body'),
                        ),
                    ))
                )
            ),
            dataset_ref=dataset_id,
            uri_scheme=scheme,
            uri_body=body,
        )

    def contains_dataset(self, dataset_id):
        return bool(self._connection.execute(select([DATASET.c.id]).where(DATASET.c.id == dataset_id)).fetchone())

    def insert_dataset_source(self, classifier, dataset_id, source_dataset_id):
        res = self._connection.execute(
            DATASET_SOURCE.insert(),
            classifier=classifier,
            dataset_ref=dataset_id,
            source_dataset_ref=source_dataset_id
        )
        return res.inserted_primary_key[0]

    def get_storage_type(self, storage_type_id):
        return self._connection.execute(
            STORAGE_TYPE.select().where(STORAGE_TYPE.c.id == storage_type_id)
        ).first()

    def get_dataset(self, dataset_id):
        return self._connection.execute(
            select(_DATASET_SELECT_FIELDS).where(DATASET.c.id == dataset_id)
        ).first()

    def get_storage_types(self, dataset_metadata):
        """
        Find any storage types that match the given dataset.

        :type dataset_metadata: dict
        :rtype: dict
        """
        # Find any storage types whose 'dataset_metadata' document is a subset of the metadata.
        return self._connection.execute(
            STORAGE_TYPE.select().where(
                STORAGE_TYPE.c.dataset_metadata.contained_by(dataset_metadata)
            )
        ).fetchall()

    def get_all_storage_types(self):
        return self._connection.execute(
            STORAGE_TYPE.select()
        ).fetchall()

    def ensure_storage_type(self,
                            name,
                            dataset_metadata,
                            definition):
        res = self._connection.execute(
            STORAGE_TYPE.insert().values(
                name=name,
                dataset_metadata=dataset_metadata,
                definition=definition
            )
        )
        return res.inserted_primary_key[0]

    def add_storage_unit(self, path, dataset_ids, descriptor, storage_type_id):
        if not dataset_ids:
            raise ValueError('Storage unit must be linked to at least one dataset.')

        # Get the collection/metadata-type for this storage unit.
        # We assume all datasets are of the same collection. (TODO: Revise when 'product type' concept is added)
        matched_collection = select([
            DATASET.c.collection_ref, DATASET.c.metadata_type_ref
        ]).where(
            DATASET.c.id == dataset_ids[0]
        ).cte('matched_collection')

        # Add the storage unit
        unit_id = self._connection.execute(
            STORAGE_UNIT.insert().values(
                collection_ref=select([matched_collection.c.collection_ref]),
                metadata_type_ref=select([matched_collection.c.metadata_type_ref]),
                storage_type_ref=storage_type_id,
                descriptor=descriptor,
                path=path
            ).returning(STORAGE_UNIT.c.id),
        ).scalar()

        # Link the storage unit to the datasets.
        self._connection.execute(
            DATASET_STORAGE.insert(),
            [
                {'dataset_ref': dataset_id, 'storage_unit_ref': unit_id}
                for dataset_id in dataset_ids
                ]
        )
        return unit_id

    def get_storage_units(self):
        return self._connection.execute(STORAGE_UNIT.select()).fetchall()

    def get_dataset_fields(self, collection_result):
        # Native fields (hard-coded into the schema)
        fields = {
            'id': NativeField(
                'id',
                None,
                None,
                DATASET.c.id
            ),
            'collection': NativeField(
                'collection',
                'Name of collection',
                None, COLLECTION.c.name
            )
        }
        dataset_search_fields = collection_result['definition']['dataset']['search_fields']

        # noinspection PyTypeChecker
        fields.update(
            parse_fields(
                dataset_search_fields,
                collection_result['id'],
                DATASET.c.metadata
            )
        )
        return fields

    def get_storage_unit_fields(self, collection_result):
        # Native fields (hard-coded into the schema)
        fields = {
            'id': NativeField(
                'id',
                None,
                collection_result['id'],
                STORAGE_UNIT.c.id
            ),
            'path': NativeField(
                'path',
                'Path to storage file',
                collection_result['id'],
                STORAGE_UNIT.c.path
            )
        }
        storage_unit_def = collection_result['definition'].get('storage_unit')
        if storage_unit_def and 'search_fields' in storage_unit_def:
            unit_search_fields = storage_unit_def['search_fields']

            # noinspection PyTypeChecker
            fields.update(
                parse_fields(
                    unit_search_fields,
                    collection_result['id'],
                    STORAGE_UNIT.c.descriptor
                )
            )

        return fields

    def search_datasets(self, expressions, select_fields=None):
        """
        :type select_fields: tuple[datacube.index.postgres._fields.PgField]
        :type expressions: tuple[datacube.index.postgres._fields.PgExpression]
        :rtype: dict
        """
        select_fields = [
            f.alchemy_expression.label(f.name)
            for f in select_fields
            ] if select_fields else _DATASET_SELECT_FIELDS

        from_expression = DATASET.join(COLLECTION)
        raw_expressions = field_expressions_to_sql(expressions)
        metadata_type_id = metadata_type_id_from_expressions(expressions)
        if metadata_type_id:
            raw_expressions = [DATASET.c.metadata_type_ref == metadata_type_id] + raw_expressions
        results = self._connection.execute(
            select(select_fields).select_from(from_expression).where(and_(*raw_expressions))
        )
        for result in results:
            yield result

    def search_storage_units(self, expressions, select_fields=None):
        """
        :type select_fields: tuple[datacube.index.postgres._fields.PgField]
        :type expressions: tuple[datacube.index.postgres._fields.PgExpression]
        :rtype: dict
        """
        select_fields = [f.alchemy_expression.label(f.name) for f in select_fields] if select_fields else [STORAGE_UNIT]

        # select_fields = [func.array_agg(DATASET.c.id).label('dataset_ids')] + select_fields
        from_expression = STORAGE_UNIT.join(DATASET_STORAGE).join(DATASET).join(COLLECTION)
        raw_expressions = field_expressions_to_sql(expressions)
        metadata_type_id = metadata_type_id_from_expressions(expressions)
        if metadata_type_id:
            raw_expressions = [STORAGE_UNIT.c.metadata_type_ref == metadata_type_id,
                               DATASET.c.metadata_type_ref == metadata_type_id] + raw_expressions
        results = self._connection.execute(
            select(select_fields).select_from(from_expression).where(and_(*raw_expressions)).group_by(STORAGE_UNIT.c.id)
        )
        for result in results:
            yield result

    def get_collection_for_doc(self, metadata_doc):
        """
        :type metadata_doc: dict
        :rtype: dict or None
        """
        return self._connection.execute(
            COLLECTION.select().where(
                COLLECTION.c.dataset_metadata.contained_by(metadata_doc)
            ).order_by(
                COLLECTION.c.match_priority.asc()
            ).limit(1)
        ).first()

    def get_collection(self, id_):
        return self._connection.execute(
            COLLECTION.select().where(COLLECTION.c.id == id_)
        ).first()

    def get_metadata_type(self, id_):
        return self._connection.execute(
            METADATA_TYPE.select().where(METADATA_TYPE.c.id == id_)
        ).first()

    def get_collection_by_name(self, name):
        return self._connection.execute(
            COLLECTION.select().where(COLLECTION.c.name == name)
        ).first()

    def get_metadata_type_by_name(self, name):
        return self._connection.execute(
            METADATA_TYPE.select().where(METADATA_TYPE.c.name == name)
        ).first()

    def get_storage_type_by_name(self, name):
        return self._connection.execute(
            STORAGE_TYPE.select().where(STORAGE_TYPE.c.name == name)
        ).first()

    def add_collection(self,
                       name,
                       dataset_metadata,
                       match_priority,
                       metadata_type_id,
                       definition):
        res = self._connection.execute(
            COLLECTION.insert().values(
                name=name,
                dataset_metadata=dataset_metadata,
                metadata_type_ref=metadata_type_id,
                match_priority=match_priority,
                definition=definition
            )
        )
        return res.inserted_primary_key[0]

    def add_metadata_type(self, name, definition):
        res = self._connection.execute(
            METADATA_TYPE.insert().values(
                name=name,
                definition=definition
            )
        )
        type_id = res.inserted_primary_key[0]
        record = self.get_metadata_type(type_id)

        # Initialise search fields.
        _setup_collection_fields(
            self._connection, name, 'dataset', self.get_dataset_fields(record),
            DATASET.c.metadata_type_ref == type_id
        )
        _setup_collection_fields(
            self._connection, name, 'storage_unit', self.get_storage_unit_fields(record),
            STORAGE_UNIT.c.metadata_type_ref == type_id
        )

    def get_all_collections(self):
        return self._connection.execute(COLLECTION.select()).fetchall()

    def count_storage_types(self):
        return self._connection.execute(select([func.count()]).select_from(STORAGE_TYPE)).scalar()

    def get_locations(self, dataset_id):
        return [
            record[0]
            for record in self._connection.execute(
                select([
                    DATASET_URI_FIELD
                ]).where(
                    DATASET_LOCATION.c.dataset_ref == dataset_id
                ).order_by(
                    DATASET_LOCATION.c.added.desc()
                )
            ).fetchall()
            ]


def _pg_exists(conn, name):
    """
    Does a postgres object exist?
    :rtype bool
    """
    return conn.execute("SELECT to_regclass(%s)", name).scalar() is not None


def _setup_collection_fields(conn, collection_prefix, doc_prefix, fields, where_expression):
    """
    Create indexes and views for a collection's search fields.
    """
    name = '{}_{}'.format(collection_prefix.lower(), doc_prefix.lower())

    # Create indexes for the search fields.
    for field in fields.values():
        index_type = field.postgres_index_type
        if index_type:
            _LOG.debug('Creating index: %s', field.name)
            index_name = 'ix_field_{prefix}_{field_name}'.format(
                prefix=name.lower(),
                field_name=field.name.lower()
            )

            if not _pg_exists(conn, schema_qualified(index_name)):
                Index(
                    index_name,
                    field.alchemy_expression,
                    postgres_where=where_expression,
                    postgresql_using=index_type,
                    # Don't lock the table (in the future we'll allow indexing new fields...)
                    postgresql_concurrently=True
                ).create(conn)

    # Create a view of search fields (for debugging convenience).
    view_name = schema_qualified(name)
    if not _pg_exists(conn, view_name):
        conn.execute(
            tables.View(
                view_name,
                select(
                    [field.alchemy_expression.label(field.name) for field in fields.values()]
                ).where(where_expression)
            )
        )


def field_expressions_to_sql(expressions):
    def raw_expr(expression):
        if isinstance(expression, OrExpression):
            return or_(raw_expr(expr) for expr in expression.exprs)
        return expression.alchemy_expression

    return [raw_expr(expression) for expression in expressions]


def fielditer(expression):
    if isinstance(expression, OrExpression):
        for expr in expression.exprs:
            for field in fielditer(expr):
                yield field
    else:
        yield expression.field


def metadata_type_id_from_expressions(expressions):
    metadata_type_references = set()
    for field in chain(*[fielditer(expr) for expr in expressions]):
        if field.metadata_type_id is not None:
            metadata_type_references.add(field.metadata_type_id)

    if len(metadata_type_references) == 0:
        return None
    elif len(metadata_type_references) == 1:
        return metadata_type_references.pop()
    else:
        raise ValueError(
            'Currently only one metadata type can be queried at a time. (Tried %r)' % metadata_type_references
        )


def _to_json(o):
    return json.dumps(o, default=_json_fallback)


def _json_fallback(obj):
    """Fallback json serialiser."""
    if isinstance(obj, (datetime.datetime, datetime.date)):
        return obj.isoformat()
    if isinstance(obj, numpy.dtype):
        return obj.name
    raise TypeError("Type not serializable: {}".format(type(obj)))


class _BegunTransaction(object):
    def __init__(self, connection):
        self._connection = connection
        self.begin()

    def begin(self):
        self._connection.execute(text('BEGIN'))

    def commit(self):
        self._connection.execute(text('COMMIT'))

    def rollback(self):
        self._connection.execute(text('ROLLBACK'))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
