# !usr/bin/env python2
# -*- coding: utf-8 -*-
#
# Licensed under a 3-clause BSD license.
#
# @Author: Brian Cherinka
# @Date:   2017-05-31 10:27:23
# @Last modified by:   Brian Cherinka
# @Last Modified time: 2017-06-01 00:36:24

import pytest
from stagemanager.stagemanager import StageManager


@pytest.fixture()
def start_sm(sm):
    sm.start_actor()
    yield sm


class TestStageManager(object):
    def test_start(self, sm, capsys):
        pid = sm.get_pid()
        assert pid is None
        sm.start_actor()
        out, err = capsys.readouterr()
        assert "Starting new {0}".format(sm.actor) in out
        assert sm.process.pid is not None

    def test_stop(self, start_sm, capsys):
        assert start_sm.process.pid is not None
        start_sm.stop_actor()
        out, err = capsys.readouterr()
        assert "Stopping product {0}".format(start_sm.actor) in out
        pid = start_sm.get_pid()
        assert pid is None

    def test_get_status(self, start_sm, capsys):
        start_sm.get_status()
        out, err = capsys.readouterr()
        assert "{0} is running".format(start_sm.actor) in out
        assert start_sm.process.pid is not None

    def test_kill(self, start_sm, capsys):
        assert start_sm.process.pid is not None
        start_sm.kill_actor()
        out, err = capsys.readouterr()
        assert "Killing product {0}".format(start_sm.actor) in out
        pid = start_sm.get_pid()
        assert pid is None

    def test_restart(self, start_sm, capsys):
        oldpid = start_sm.get_pid()
        start_sm.restart_actor()
        newpid = start_sm.get_pid()
        out, err = capsys.readouterr()
        assert oldpid != newpid
        assert "Stopping product {0}".format(start_sm.actor) in out
        assert "Starting new {0}".format(start_sm.actor) in out

    def test_getprocesses(self, start_sm):
        procs = start_sm.get_processes()
        assert procs is not None

    def test_listprocesses(self, start_sm, capsys):
        start_sm.list_processes()
        out, err = capsys.readouterr()
        assert start_sm.actor in out


class TestStageSetupEnv(object):
    @pytest.mark.parametrize("name", [("modules"), ("eups")])
    def test_no_setups(self, sm, unload, name):
        prodpath = sm._get_actor_path()
        assert prodpath is None
        with pytest.raises(RuntimeError):
            sm.__getattribute__("_try_{0}".format(name))()

    @pytest.mark.parametrize(
        "host, user, errmsg",
        [
            (None, None, "Current Host must be sdss4-hub"),
            (True, None, "Current User must be sdss4"),
        ],
        ids=["wronghost", "wronguser"],
    )
    def test_wrongsystem(self, actor, host, user, errmsg):
        with pytest.raises(AssertionError) as cm:
            StageManager(actor=actor, overhost=host, overuser=user)
        assert errmsg in str(cm.value)
