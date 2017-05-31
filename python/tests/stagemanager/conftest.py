# !usr/bin/env python2
# -*- coding: utf-8 -*-
#
# Licensed under a 3-clause BSD license.
#
# @Author: Brian Cherinka
# @Date:   2017-05-31 10:27:32
# @Last modified by:   Brian Cherinka
# @Last Modified time: 2017-05-31 11:33:23

from __future__ import print_function, division, absolute_import
from stagemanager.stagemanager import StageManager
import pytest
import socket
import os

actors = ['sopActor']


@pytest.fixture(params=actors)
def actor(request):
    return request.param


@pytest.fixture(scope='session')
def ishub():
    hubhost = 'hub' in socket.gethostname()
    sdssuser = 'sdss' in os.environ.get('USER', None)
    return all([hubhost, sdssuser])


@pytest.fixture()
def sm(actor, ishub):
    if ishub:
        sm = StageManager(actor=actor)
    else:
        sm = StageManager(actor=actor, overhost=True, overuser=True)
    yield sm
    pid = sm.get_pid()
    if pid:
        print(pid)
        print(sm.process)
        sm.stop_actor()
    sm = None








