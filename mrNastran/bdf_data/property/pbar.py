from __future__ import print_function, absolute_import
from six import iteritems, itervalues
from six.moves import range

from tables import IsDescription, Int64Col, Float64Col, StringCol
import tables

from .._abstract_table import AbstractTable
from ._property import PropertyCard

import numpy as np


class PbarTable(AbstractTable):
    group = '/NASTRAN/INPUT/PROPERTY'
    table_id = 'PBAR'
    table_path = '%s/%s' % (group, table_id)

    dtype = np.dtype([
        ('PID', np.int64),
        ('MID', np.int64),
        ('A', np.float64),
        ('I1', np.float64),
        ('I2', np.float64),
        ('J', np.float64),
        ('NSM', np.float64),
        ('C1', np.float64),
        ('C2', np.float64),
        ('D1', np.float64),
        ('D2', np.float64),
        ('E1', np.float64),
        ('E2', np.float64),
        ('F1', np.float64),
        ('F2', np.float64),
        ('K1', np.float64),
        ('K2', np.float64),
        ('I12', np.float64),
        ('DOMAIN_ID', np.int64)
    ])

    Format = tables.descr_from_dtype(dtype)[0]

    @classmethod
    def _write_data(cls, h5f, cards, h5table):
        table_row = h5table.row

        domain = cls.domain_count

        ids = sorted(cards.keys())

        for _id in ids:
            data = cards[_id]
            """:type data: pyNastran.bdf.cards.properties.bars.PBAR"""

            table_row['PID'] = data.pid
            table_row['MID'] = data.mid
            table_row['A'] = data.A
            table_row['I1'] = data.i1
            table_row['I2'] = data.i2
            table_row['J'] = data.j
            table_row['NSM'] = data.nsm
            table_row['C1'] = data.c1
            table_row['C2'] = data.c2
            table_row['D1'] = data.d1
            table_row['D2'] = data.d2
            table_row['E1'] = data.e1
            table_row['E2'] = data.e2
            table_row['F1'] = data.f1
            table_row['F2'] = data.f2
            table_row['K1'] = data.k1
            table_row['K2'] = data.k2

            table_row['DOMAIN_ID'] = domain

            table_row.append()

        h5f.flush()


class PBAR(PropertyCard):
    table_reader = PbarTable
    dtype = table_reader.dtype
