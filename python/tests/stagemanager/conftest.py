# !usr/bin/env python2
# -*- coding: utf-8 -*-
#
# Licensed under a 3-clause BSD license.
#
# @Author: Brian Cherinka
# @Date:   2017-05-31 10:27:32
# @Last modified by:   Brian Cherinka
# @Last Modified time: 2017-05-31 19:00:23

from __future__ import print_function, division, absolute_import
from stagemanager.stagemanager import StageManager
import pytest
import socket
import os
import sys
import copy

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
def unload(actor, monkeypatch):
    actorpath = '{0}_DIR'.format(actor.upper())
    monkeypatch.delenv(actorpath)
    syscopy = copy.deepcopy(sys.path)
    monkeypatch.setattr(sys, 'path', syscopy)
    pypath = [item for item in sys.path if actor in item]
    sys.path.remove(pypath[0])


@pytest.fixture()
def sm(actor, ishub, tmpdir):
    logdir = str(tmpdir.mkdir("logs"))
    if ishub:
        sm = StageManager(actor=actor, logdir=logdir)
    else:
        sm = StageManager(actor=actor, overhost=True, overuser=True, logdir=logdir)
    yield sm
    pid = sm.get_pid()
    if pid:
        sm.stop_actor()
    sm = None







