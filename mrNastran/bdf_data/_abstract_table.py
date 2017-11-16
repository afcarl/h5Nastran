"""
"""
from __future__ import print_function, absolute_import
from six import iteritems, itervalues
from six.moves import range


import tables
import numpy as np


class AbstractTable(object):

    group = ''
    table_id = ''
    table_path = ''

    domain_count = 1

    dtype = None  # numpy dtype for card data
    Format = None  # pytables description for table

    @classmethod
    def write_data(cls, h5f, table_data):
        cls._write_data(h5f, table_data, cls.get_data_table(h5f))

    @classmethod
    def _write_data(cls, h5f, table_data, h5table):
        raise NotImplementedError

    @classmethod
    def get_data_table(cls, h5f, expected_rows=1000000):
        try:
            return h5f.get_node(cls.table_path)
        except tables.NoSuchNodeError:
            # print(cls.Format)
            return h5f.create_table(cls.group, cls.table_id, cls.Format, cls.table_id,
                                    expectedrows=expected_rows, createparents=True)

    @classmethod
    def finalize(cls, h5f):
        pass

    @classmethod
    def read(cls, h5f):
        try:
            table = h5f.get_node(cls.table_path)
        except tables.NoSuchNodeError:
            return None

        return table.read()

