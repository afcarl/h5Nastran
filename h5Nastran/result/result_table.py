from __future__ import print_function, absolute_import

from collections import defaultdict
from copy import deepcopy

import numpy as np
import tables

from h5Nastran.msc import data_tables
from ..punch import PunchTableData


########################################################################################################################


def _get_dtype(table):
    try:
        return data_tables[table.same_as].dtype
    except KeyError:
        return table.dtype


########################################################################################################################


class _Format(object):
    def __init__(self):
        raise NotImplementedError


class IndexFormat(tables.IsDescription):
    DOMAIN_ID = tables.Int64Col(pos=1)
    POSITION = tables.Int64Col(pos=2)
    LENGTH = tables.Int64Col(pos=3)


class PrivateIndexFormat(tables.IsDescription):
    LOCATION = tables.Int64Col(pos=1)
    LENGTH = tables.Int64Col(pos=2)
    OFFSET = tables.Int64Col(pos=3)


private_index_format_dtype = tables.dtype_from_descr(PrivateIndexFormat)


class PrivateIndexDataFormat(tables.IsDescription):
    ID = tables.Int64Col(pos=1)


private_index_data_format_dtype = tables.dtype_from_descr(PrivateIndexDataFormat)

########################################################################################################################


def _validator(data):
    return data

########################################################################################################################


def _convert_dtype(dtype, indices):
    new_dtype = []
    new_indices = DataGetter()

    for i in range(len(dtype)-1):
        _dtype = dtype[i]
        _indices = indices.indices[i]

        if not isinstance(_dtype[1], list):
            new_dtype.append(_dtype)
            new_indices.indices.append(_indices)
        else:
            for j in range(len(_dtype[1])):
                _ = _dtype[1][j]
                assert not isinstance(_, list)  # not doing multiple levels
                _name = _[0]
                _type = _[1]
                if len(_indices) == 1:
                    _shape = ()
                    new_indices.indices.append(_indices[0][j])
                else:
                    _shape = (len(_indices),)
                    new_indices.indices.append([_[j] for _ in _indices])

                new_dtype.append((_name, _type, _shape))

    new_dtype.append(dtype[-1])  # add DOMAIN_ID

    return new_dtype, new_indices

########################################################################################################################


class DefinedValue(object):
    def __init__(self, value):
        self.value = value


class DataGetter(object):
    def __init__(self, dtype=None, indices=None):
        self.indices = []

        if dtype is not None:
            self.make_indices_from_dtype(dtype)

        if indices is not None:
            self.indices = deepcopy(indices)

    def __len__(self):
        return len(self.indices)

    def make_indices_from_dtype(self, dtype):
        del self.indices[:]

        def _make_indices(_dtype, i):
            indices = []

            for _ in _dtype:
                if i == 1:
                    i = 2  # skip 2nd field in punch file by default

                _d = _[1]
                shape = _[2]
                try:
                    size = shape[0]
                except IndexError:
                    size = 1

                if isinstance(_d, list):
                    _indices = _make_indices(_d, i)

                    if size > 1:
                        _list_indices = [_indices]
                        for j in range(size-1):
                            _list_indices.append((np.array(_list_indices[-1]) + len(_list_indices[-1])).tolist())
                        _indices = _list_indices
                    else:
                        _indices = [_indices]

                    def _count(_indices_):
                        _result = 0
                        for _i in _indices_:
                            if isinstance(_i, list):
                                _result += _count(_i)
                            else:
                                _result += 1

                        return _result

                    i += _count(_indices)
                    indices.append(_indices)
                else:
                    indices.append(i)
                    i += size

            return indices

        self.indices.extend(_make_indices(dtype, 0))
        self.indices.pop()

    def get_data(self, data, indices=None):
        result = []

        if indices is None:
            indices = self.indices

        for i in indices:
            if isinstance(i, list):
                result.append(self.get_data(data, i))
            elif isinstance(i, (int, slice)):
                result.append(data[i])
            elif isinstance(i, DefinedValue):
                result.append(i.value)
            else:
                result.append(data[i])

        return result


def _get_data(data, index):
    if isinstance(index, (int, slice)):
        return data[index]
    elif isinstance(index, (list, tuple)):
        return [_get_data(data, i) for i in index]
    elif isinstance(index, DefinedValue):
        return index.value
    elif isinstance(index, DataGetter):
        return index.get_data(data)
    else:
        raise TypeError('Unknown index type! %s' % str(type(index)))

########################################################################################################################


class TableDef(object):

    @classmethod
    def create(cls, table_def, results_type, indices=None, validator=None, len_id=None, pos_id=None, subtables=None, rename=None,
               is_subtable=False):
        if isinstance(table_def, str):
            table_def = data_tables[table_def]
        try:
            dtype = data_tables[table_def.same_as].dtype
        except KeyError:
            dtype = table_def.dtype
        index_id = dtype[0][0]
        if indices is None:
            indices = DataGetter(dtype)
        for _ in dtype:
            if isinstance(_[1], list):
                # need to convert dtype since pytables doesn't support nested dtypes
                dtype, indices = _convert_dtype(dtype, indices)
                break
        if subtables is None:
            subtables = [TableDef.create(data_tables[_], '', rename=rename, is_subtable=True) for _ in table_def.subtables]
        return cls(table_def.name, table_def.path, results_type, index_id, dtype, indices, validator,
                   len_id, pos_id, subtables, rename, is_subtable=is_subtable)

    def __init__(self, table_id, group, results_type, index_id, dtype, indices, validator=None,
                 len_id=None, pos_id=None, subtables=None, rename=None, is_subtable=False):
        self.implemented = True
        self.table_id = table_id
        self.group = group

        self.dtype = np.dtype(dtype)

        if subtables is None:
            subtables = []

        assert len(subtables) == 0, 'Cannot have subtables defined for this result table type.'

        self.subtables = subtables

        self.attrs = list(self.dtype.names)

        try:
            self.attrs.remove('DOMAIN_ID')
        except ValueError:
            pass

        def _zero():
            return 0

        self._pos = defaultdict(_zero)

        for subtable in self.subtables:
            try:
                self.attrs.remove(subtable.pos_id)
                self.attrs.remove(subtable.len_id)
            except ValueError:
                print(self.path(), self.attrs, subtable.pos_id, subtable.len_id)
                raise

        self.table = None

        self.h5f = None

        if len_id is None:
            len_id = '%s_LEN' % self.table_id.replace('_', '')

        if pos_id is None:
            pos_id = '%s_POS' % self.table_id.replace('_', '')

        if rename is None:
            rename = {}

        self.len_id = rename.get(len_id, len_id)
        self.pos_id = rename.get(pos_id, pos_id)

        cols = set(self.dtype.names)

        for subtable in self.subtables:
            assert subtable.len_id in cols
            assert subtable.pos_id in cols

        ################################################################################################################

        self.is_subtable = is_subtable

        self.index_id = index_id

        try:
            self.results_type = results_type[0]
        except IndexError:
            self.results_type = results_type

        if validator is None:
            validator = _validator

        self.validator = validator

        try:
            self.Format = tables.descr_from_dtype(self.dtype)[0]
        except NotImplementedError:
            dtype, indices = _convert_dtype(dtype, indices)
            self.dtype = np.dtype(dtype)
            self.Format = tables.descr_from_dtype(self.dtype)[0]

        self.indices = deepcopy(indices)

        assert isinstance(self.indices, DataGetter)

        assert len(self.indices) == len(self.dtype.names) - 1

        self.domain_count = 0

        self.IndexFormat = IndexFormat
        self.PrivateIndexFormat = PrivateIndexFormat
        self.PrivateIndexDataFormat = PrivateIndexDataFormat

        self._index_table = None
        self._private_index_table = None

        self._index_data = []
        self._subcase_index = []
        self._index_offset = 0

    def __deepcopy__(self, memodict=None):
        from copy import copy
        _copy = copy(self)
        _copy.domain_count = 0
        _copy._index_offset = 0
        del _copy._index_data[:]
        del _copy._subcase_index[:]
        _copy._index_table = None
        _copy._private_index_table = None

        memodict[id(_copy)] = _copy

        return _copy

    def finalize(self):
        if self.is_subtable:
            return
        self._write_index()
        self._write_private_index()

    def get_table(self):
        if self.table is None:
            self.table = self._make_table()
        return self.table

    def not_implemented(self):
        self.implemented = False

    def read(self, indices):
        table = self.get_table()

        indices = np.array(indices, dtype='i8')

        data = np.empty(len(indices), dtype=table._v_dtype)
        table._read_elements(indices, data)

        return data

    def search(self, domains, data_ids, filter=None):
        private_index_table = self._get_private_index_table()

        indices = set()

        for domain in domains:
            try:
                index_dict, offset = private_index_table[domain-1]
            except IndexError:
                continue

            for data_id in data_ids:
                _indices = index_dict[data_id]
                indices.update(set(index + offset for index in _indices))

        results = self.read(sorted(indices))

        if filter is not None:
            indices = set()
            for key in filter.keys():
                data = set(filter[key])
                results_data = results[key]
                for i in range(results_data.shape[0]):
                    if results_data[i] in data:
                        indices.add(i)
            results = results[sorted(indices)]

        return results

    def path(self):
        return self.group + '/' + self.table_id

    def set_h5f(self, h5f):
        self.h5f = h5f
        for subtable in self.subtables:
            subtable.set_h5f(h5f)

    def to_numpy(self, data):
        result = np.empty(len(data), dtype=self.dtype)

        validator = self.validator

        names = list(self.dtype.names)

        _result = {name: result[name] for name in names}

        for i in range(len(data)):
            _data = validator(self.indices.get_data(data[i]))
            _data.append(self.domain_count)

            for j in range(len(names)):
                _result[names[j]][i] = _data[j]

        return result

    def write_data(self, data):
        assert isinstance(data, PunchTableData)

        if len(data.data) == 0:
            return

        table = self.get_table()

        self.domain_count += 1

        data = self.to_numpy(data.data)
        table.append(data)
        self._record_data_indices(data)

        self.h5f.flush()

    def _get_index_table(self):
        if self.is_subtable:
            return None
        h5f = self.h5f
        if self._index_table is None:
            index_table = h5f.get_node('/INDEX%s' % self.path())
            index_table = index_table.read()

            self._index_table = [
                set(range(index_table['POSITION'][i], index_table['POSITION'][i] + index_table['LENGTH'][i]))
                for i in range(index_table.shape[0])
            ]

        return self._index_table

    def _get_private_index_table(self):
        if self.is_subtable:
            return None
        h5f = self.h5f
        if self._private_index_table is None:
            data = h5f.get_node(self._private_index_path + '/DATA')
            data = data.read()

            identity = h5f.get_node(self._private_index_path + '/IDENTITY')
            identity = identity.read()

            private_index_table = self._private_index_table = []

            _index_data = {}

            for i in range(identity.shape[0]):
                location, length, offset = identity[i]

                try:
                    private_index_table.append((_index_data[location][0], offset))
                except KeyError:
                    _data_dict = load_data_dict(data['ID'][location: location + length])
                    _index_data[location] = (_data_dict, offset)
                    private_index_table.append(_index_data[location])

        return self._private_index_table

    def _get_private_index_tables(self):
        if self.is_subtable:
            return None, None
        h5f = self.h5f
        try:
            identity = h5f.get_node(self._private_index_path + '/IDENTITY')
        except tables.NoSuchNodeError:
            identity = h5f.create_table(self._private_index_path, 'IDENTITY', self.PrivateIndexFormat, 'Private Index',
                                        expectedrows=len(self._subcase_index), createparents=True)
        try:
            data = h5f.get_node(self._private_index_path + '/DATA')
        except tables.NoSuchNodeError:
            data = h5f.create_table(self._private_index_path, 'DATA', self.PrivateIndexDataFormat, 'Private Index Data',
                                    expectedrows=sum([len(_) for _ in self._index_data]), createparents=True)

        return identity, data

    def _make_table(self, expected_rows=100000):
        if self.implemented is False:
            return None
        try:
            return self.h5f.get_node(self.path())
        except tables.NoSuchNodeError:
            try:
                self.h5f.create_table(self.group, self.table_id, self.Format, self.table_id,
                                        expectedrows=expected_rows, createparents=True)
            except tables.FileModeError:
                return None
            return self.h5f.get_node(self.path())

    @property
    def _private_index_path(self):
        return '/PRIVATE/INDEX' + self.path()

    def _record_data_indices(self, data):
        if self.is_subtable:
            return

        serialized_data = serialize_indices(data[self.index_id][:])

        index_data = serialized_data.astype(dtype=private_index_data_format_dtype)

        found_index = False

        index_data_offset = 0

        for i in range(len(self._index_data)):
            _index_data = self._index_data[i]
            if _index_data.shape == index_data.shape:
                if np.all(_index_data == index_data):
                    self._subcase_index.append((index_data_offset, index_data.shape[0], self._index_offset))
                    found_index = True
                    break
            index_data_offset += _index_data.shape[0]

        if not found_index:
            self._index_data.append(index_data)
            self._subcase_index.append((index_data_offset, index_data.shape[0], self._index_offset))

        self._index_offset += data.shape[0]

    def _write_index(self):
        if self.is_subtable:
            return

        table = self.get_table()

        # noinspection PyProtectedMember
        domain_id = table.cols._f_col('DOMAIN_ID')[:]

        unique, counts = np.unique(domain_id, return_counts=True)
        counts = dict(zip(unique, counts))

        domains = self.h5f.create_table('/INDEX' + self.group, self.table_id, self.IndexFormat, self.results_type,
                                   expectedrows=len(counts), createparents=True)

        row = domains.row

        pos = 0

        for i in range(len(counts)):
            d = i + 1
            count = counts[d]

            row['DOMAIN_ID'] = d
            row['POSITION'] = pos
            row['LENGTH'] = count

            row.append()

            pos += count

        domains.flush()

        self._index_table = None

    def _write_private_index(self):
        if self.is_subtable:
            return

        identity, data = self._get_private_index_tables()

        identity.append(np.array(self._subcase_index, dtype=private_index_format_dtype))

        for index_data in self._index_data:
            data.append(index_data)

        self.h5f.flush()

        self._private_index_table = None

        del self._subcase_index[:]
        del self._index_data[:]

########################################################################################################################


def serialize_indices(data):
    return serialize_data_dict(get_data_dict(data))


def get_data_dict(data):
    from collections import OrderedDict
    data_dict = OrderedDict()

    for i in range(data.shape[0]):
        data_id = int(data[i])
        try:
            data_dict[data_id].append(i)
        except KeyError:
            data_dict[data_id] = [i]

    return data_dict


def serialize_data_dict(data_dict):
    data = []

    for key, _data in data_dict.items():
        _data_ = [key, len(_data)]
        _data_.extend(_data)
        data.extend(_data_)

    return np.array(data)


def load_data_dict(serialize_data, offset=0):
    data_dict = {}

    last_i = serialize_data.shape[0] - 1

    i = 0
    while True:
        data_id = serialize_data[i]
        data_len = serialize_data[i + 1]

        _data = serialize_data[i + 2: i + 2 + data_len]

        data_dict[data_id] = _data + offset

        i += 2 + data_len

        if i >= last_i:
            break

    assert i == last_i + 1

    return data_dict


########################################################################################################################


class TableData(object):
    def __init__(self, data=None, subdata_len=None, subdata=None):

        if data is None:
            data = []

        if subdata_len is None:
            subdata_len = np.zeros((1, 1))

        if subdata is None:
            subdata = []

        self.data = data
        self.subdata_len = subdata_len  # type: np.ndarray
        self.subdata = subdata  # type: list[TableData]

    def __repr__(self):
        result = [str(self.data)]
        for subdata in self.subdata:
            result.append(subdata.__repr__())
        return ';'.join(result)

    def validate(self):
        if len(self.subdata) > 0:
            shape = self.subdata_len.shape
            assert shape[0] == len(self.data), (shape[0], len(self.data))
            assert shape[1] == len(self.subdata), (shape[1], len(self.subdata))
        for subdata in self.subdata:
            subdata.validate()


class ResultTable(object):
    result_type = ''
    table_def = None  # type: TableDef

    def __init__(self, h5n, parent):
        self._h5n = h5n
        self._parent = parent
        self._table_def = deepcopy(self.table_def)
        self._table_def.set_h5f(self._h5n.h5f)

        if self.result_type is not None:
            self._h5n.register_result_table(self)

    def write_data(self, data):
        self._table_def.write_data(data)

    def finalize(self):
        self._table_def.finalize()

    def read(self, indices):
        return self._table_def.read(indices)

    def search(self, domains, data_ids, filter=None):
        return self._table_def.search(domains, data_ids, filter)
