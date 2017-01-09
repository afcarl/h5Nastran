"""
Copyright (C) Michael James Redmond, Jr - All Rights Reserved
Unauthorized copying of this file, via any medium is strictly prohibited
Proprietary and confidential
Written by Michael James Redmond, Jr.
"""
from __future__ import print_function, absolute_import

from nastran_database import NastranDatabase


pchfile = r'./files/wing_punchandpost.pch'
bdffile = r'./files/wing.bdf'


db = NastranDatabase('test.h5', 'w')


db.read(bdffile, pchfile)
