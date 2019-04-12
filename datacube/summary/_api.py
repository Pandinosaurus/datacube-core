from typing import Optional
import json
import logging
from collections import namedtuple
from datetime import datetime

from sqlalchemy import select, func
from datacube.index import Index, fields
from datacube.model import Dataset
from datacube.drivers.postgres._fields import DateDocField, NativeField, SimpleDocField
from datacube.drivers.postgres._schema import DATASET
from datacube.utils import geometry, cached_property

from ._schema import PRODUCT_SUMMARIES

_LOG = logging.getLogger(__name__)


class DatasetLight(object):
    def __init__(self, uuid, grid_spatial, time=None, **kwargs):
        self._gs = grid_spatial
        self.id = uuid
        self.time = time
        self.search_fields = kwargs

    @property
    def crs(self) -> Optional[geometry.CRS]:
        """ Return CRS if available
        """

        return Dataset.crs.__get__(self)

    @property
    def extent(self) -> Optional[geometry.Geometry]:
        """ :returns: valid extent of the dataset or None
        """

        return Dataset.extent.__get__(self, DatasetLight)

    @property
    def center_time(self) -> Optional[datetime]:
        """ mid-point of time range
        """
        time = self.time
        if time is None:
            return None
        return time.begin + (time.end - time.begin) // 2


class SummaryAPI:  # pylint: disable=protected-access
    def __init__(self, index: Index):
        self._index = index
        # self._engine = index._db._engine  # pylint: disable=protected-access

    def get_summaries(self, **kwargs):
        return self._index._db._engine.execute(
            select(
                [PRODUCT_SUMMARIES]
            ).where(
                PRODUCT_SUMMARIES.c.query == kwargs
            )
        ).first()

    def get_product_time_min(self, product: str):

        # Get the offsets of min time in dataset doc
        product = self._index.products.get_by_name(product)
        dataset_section = product.metadata_type.definition['dataset']
        min_offset = dataset_section['search_fields']['time']['min_offset']

        time_field = DateDocField('aquisition_time_min',
                                  'Min of time when dataset was acquired',
                                  DATASET.c.metadata,
                                  False,  # is it indexed ToDo
                                  offset=min_offset,
                                  selection='least')

        result = self._index._db._engine.execute(
            select([func.min(time_field.alchemy_expression)]).where(
                DATASET.c.dataset_type_ref == product.id
            )
        ).first()

        return result[0]

    def get_product_time_max(self, product: str):

        # Get the offsets of min time in dataset doc
        product = self._index.products.get_by_name(product)
        dataset_section = product.metadata_type.definition['dataset']
        max_offset = dataset_section['search_fields']['time']['max_offset']

        time_field = DateDocField('aquisition_time_max',
                                  'Max of time when dataset was acquired',
                                  DATASET.c.metadata,
                                  False,  # is it indexed ToDo
                                  offset=max_offset,
                                  selection='greatest')

        result = self._index._db._engine.execute(
            select([func.max(time_field.alchemy_expression)]).where(
                DATASET.c.dataset_type_ref == product.id
            )
        ).first()

        return result[0]

    # pylint: disable=redefined-outer-name
    def search_returing_datasets_light(self, field_names: tuple, limit=None, **query):

        assert field_names

        for product, query_exprs in self.make_query_expr(query):

            select_fields, fields_to_process = self.make_search_fields(product, field_names)

            result_type = namedtuple('DatasetLight', tuple(field.name for field in select_fields))

            class DatasetLight(result_type):

                if fields_to_process.get('grid_spatial'):
                    @property
                    def _gs(self):
                        return self.grid_spatial

                    @property
                    def crs(self):
                        return Dataset.crs.__get__(self)

                    @property
                    def extent(self):
                        return Dataset.extent.__get__(self, Dataset)

            with self._index._db.connect() as connection:
                results = connection.search_datasets(
                    query_exprs,
                    select_fields=select_fields,
                    limit=limit
                )

            for result in results:
                field_values = {field.name: result[i_] for i_, field in enumerate(select_fields)}
                if 'grid_spatial' in fields_to_process:
                    field_values['grid_spatial'] = json.loads(field_values['grid_spatial'])
                yield DatasetLight(**field_values)

    def make_search_fields(self, product, field_names):

        assert product and field_names

        dataset_fields = product.metadata_type.dataset_fields
        dataset_section = product.metadata_type.definition['dataset']

        select_fields = []
        fields_to_process = dict()
        for field_name in field_names:
            if dataset_fields.get(field_name):
                select_fields.append(dataset_fields[field_name])
            else:
                # try to construct the field
                if field_name in {'grid_spatial', 'extent', 'crs'}:
                    grid_spatial = dataset_section.get('grid_spatial')
                    if grid_spatial:
                        select_fields.append(SimpleDocField(
                            'grid_spatial', 'grid_spatial', DATASET.c.metadata,
                            False,
                            offset=grid_spatial
                        ))
                    if field_name in {'extent', 'crs'}:
                        if not fields_to_process.get('grid_spatial'):
                            fields_to_process['grid_spatial'] = set()
                        fields_to_process['grid_spatial'].add(field_name)

        return select_fields, fields_to_process

    def make_source_expr(self, source_filter):

        assert source_filter

        product_queries = list(self._index.datasets._get_product_queries(source_filter))
        if not product_queries:
            # No products match our source filter, so there will be no search results regardless.
            raise ValueError('No products match source filter: ' % source_filter)
        if len(product_queries) > 1:
            raise RuntimeError("Multi-product source filters are not supported. Try adding 'product' field")

        source_queries, source_product = product_queries[0]
        dataset_fields = source_product.metadata_type.dataset_fields

        return tuple(fields.to_expressions(dataset_fields.get, **source_queries))

    def make_query_expr(self, query):

        product_queries = list(self._index.datasets._get_product_queries(query))
        if not product_queries:
            raise ValueError('No products match search terms: %r' % query)

        for q, product in product_queries:
            dataset_fields = product.metadata_type.dataset_fields
            query_exprs = tuple(fields.to_expressions(dataset_fields.get, **q))
            yield product, query_exprs
