# !usr/bin/env python2
# -*- coding: utf-8 -*-
#
# Licensed under a 3-clause BSD license.
#
# @Author: Brian Cherinka
# @Date:   2017-05-30 16:07:27
# @Last modified by:   Brian Cherinka
# @Last Modified time: 2017-05-31 12:37:14

from __future__ import print_function, division, absolute_import
from argparse import ArgumentParser
import subprocess
import os
import psutil
import datetime
import socket


class StageManager(object):

    def __init__(self, console=None, actor=None, logdir=None, overuser=None, overhost=None):
        self.args = {}
        self.actor = actor
        self.process = None
        self.logdir = logdir if logdir else os.path.join(os.path.expanduser('~'), 'logs')
        self.overuser = overuser
        self.overhost = overhost

        # parse any command-line arguments
        if console:
            self.parse_args()

        # set up environ
        self.set_envs()

        # check the user/host
        if self.actor:
            self.check_user_host()

        # run functions if command-line was used
        if self.args:
            self.args.func()

    def parse_args(self):
        ''' Parse the arguments for stageManager '''
        parser = ArgumentParser(prog='stageManager', usage='%(prog)s [options]')
        subparsers = parser.add_subparsers()

        parent = ArgumentParser(add_help=False)
        parent.add_argument('actor', type=str, help='name of the actor to manage', default=None)
        parser_start = subparsers.add_parser('start', parents=[parent], help='start an actor')
        parser_stop = subparsers.add_parser('stop', parents=[parent], help='stop an actor')
        parser_kill = subparsers.add_parser('kill', parents=[parent], help='kill an actor')
        parser_status = subparsers.add_parser('status', parents=[parent], help='get the status of an actor')
        parser_start.set_defaults(func=self.start_actor)
        parser_stop.set_defaults(func=self.stop_actor)
        parser_kill.set_defaults(func=self.kill_actor)
        parser_status.set_defaults(func=self.get_status)

        parser.add_argument('-l', '--logdir', type=str, dest='logdir', help='path to write log files', default=os.path.join(os.path.expanduser('~'), 'logs'))
        parser.add_argument('-u', '--overrideuser', dest='overuser', help='override to the current user', action='store_true', default=False)
        parser.add_argument('-o', '--overridehost', dest='overhost', help='override to the current host', action='store_true', default=False)

        self.args = parser.parse_args()
        # set the actor
        assert self.args.actor is not None, 'an actor must be specified'
        for arg, val in self.args.__dict__.items():
            self.__setattr__(arg, val)

    def start_actor(self):
        ''' Start an actor '''
        pid = self.get_pid()
        if not pid:
            print('Starting new {0} ...'.format(self.actor))
            # check the paths
            product_path = self._get_actor_path()
            actorbin = os.path.join(product_path, 'bin', '{0}_main.py'.format(self.actor))
            oldactor = os.path.join(product_path, 'python/{0}'.format(self.actor), '{0}_main.py'.format(self.actor))
            # use the new actor_main in bin if it exists
            if os.path.isfile(actorbin):
                actorpath = actorbin
            elif os.path.isfile(oldactor):
                actorpath = oldactor
            else:
                raise NameError('Cannot find the {0}_main.py'.format(self.actor))

            # create logfile based on current time
            nowlog = datetime.datetime.now().utcnow().isoformat() + '.log'
            logdir = os.path.join(self.product_logs_dir, nowlog)

            # start the actor
            actorcmd = 'python {0} > {1} 2>&1 &'.format(actorpath, logdir)
            p = subprocess.Popen(actorcmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            (out, err) = p.communicate()

            # check error
            if 'error' in out.lower():
                raise RuntimeError('Failed to start the actor {0}!'.format(self.actor))

        # check status
        self.get_status()

    def get_status(self):
        ''' Get the status of an actor '''
        pid = self.get_pid()
        if pid:
            print('{0} is running as process {1}'.format(self.actor, pid))
        else:
            print('{0} is not running!'.format(self.actor))

    def stop_actor(self, kill=None):
        ''' Stop the actor '''
        pid = self.get_pid()
        if pid:
            stopcmd = 'Killing' if kill else 'Stopping'
            print('{0} product {1}'.format(stopcmd, self.actor))
            if kill:
                self.process.kill()
            else:
                self.process.terminate()
            self.process = None

    def kill_actor(self):
        ''' Kill the actor '''
        self.stop_actor(kill=True)

    def get_pid(self):
        ''' Get the pid of a given actor '''
        self.get_process()
        if self.process:
            pid = self.process.pid
        else:
            pid = None
        return pid

    def get_processes(self):
        ''' Gets a list of all actor processess running '''
        actors = self._parse_config()
        procs = []
        for proc in psutil.process_iter():
            pdict = proc.as_dict(attrs=['pid', 'name'])
            name = pdict.get('name', None)
            if name and 'python' in name:
                proccmd = proc.cmdline()[1]
                if any([a for a in actors if a in proccmd]):
                    procs.append(proc)
        return procs

    def list_processes(self):
        ''' List all the running processes '''
        procs = self.get_processes()
        for p in procs:
            cmd = p.cmdline()[1]
            name = cmd.rsplit('/', 1)[-1].split('_')[0]
            print(name, p.pid)

    def get_process(self):
        ''' Gets the process for the given actor '''
        for proc in psutil.process_iter():
            pdict = proc.as_dict(attrs=['pid', 'name'])
            name = pdict.get('name', None)
            if name and 'python' in name:
                proccmd = proc.cmdline()
                if self.actor in proccmd[1]:
                    self.process = proc

    def set_envs(self):
        ''' Set up the necessary environment variables '''
        self.current_actorcore_dir = os.environ.get('ACTORCORE_DIR', None)

        # set up product path
        if self.actor:
            product_path = self._get_actor_path()
            if not product_path:
                print('Product {0} is not setup. Trying..'.format(self.actor))
                self.setup_actor()

            # try again
            product_path = self._get_actor_path()
            if product_path:
                self.is_product_setup = True
                self.product_logs_dir = os.path.join(self.logdir, self.actor)
                if not os.path.isdir(self.product_logs_dir):
                    os.makedirs(self.product_logs_dir)

    def _get_actor_path(self):
        ''' Returns the actor product path '''
        product_dir = '{0}_DIR'.format(self.actor.upper())
        product_path = os.environ.get(product_dir, None)
        return product_path

    def setup_actor(self):
        ''' Attempt to setup the actor with modules '''

        product_path = self._get_actor_path()
        module_cmd = 'module -v load {0}'.format(self.actor)

        # run the module process
        p = subprocess.Popen(module_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        (out, err) = p.communicate()

        # check it
        if 'ERROR' in out:
            raise RuntimeError('Could not setup product {0}.  Please setup manually.'.format(self.actor))

    def _read_the_config(self):
        ''' Read the stage manager config file '''
        sm_cfg = os.path.join(self.current_actorcore_dir, 'etc/stageManager.cfg')
        f = open(sm_cfg, 'r')
        data = f.read().splitlines()
        f.close()
        return data

    def _parse_config(self):
        ''' Parse the config file into a list of actors '''
        data = self._read_the_config()
        actors = [line.split('=')[0].strip() for line in data if line and '#' not in line]
        return actors

    def check_user_host(self):
        ''' Check the username and hosts '''

        # read in the stage manager config
        data = self._read_the_config()

        # find the actor in the config and extract user and host
        actor_cfg = [line for line in data if self.actor in line]
        if not actor_cfg:
            raise IndexError('No user/host config information found for {0}.  \
                Consider adding it to etc/stageManager.cfg'.format(self.actor))
        else:
            userhost = actor_cfg[0].split('=')[1]
            user, host = userhost.strip().split('@')

            currenthost = os.environ.get('HOSTNAME', socket.gethostname())
            currentuser = os.environ.get('USER', None)

            if self.overhost and currenthost:
                print('Overriding hostname with {0}'.format(currenthost))
                os.environ['HOSTNAME'] = currenthost
            elif not self.overhost:
                assert currenthost == host, 'Current Host must be {0}'.format(host)
            else:
                print('Cannot override host.  Could not find current hostname!')

            if self.overuser:
                print('Overriding user with {0}'.format(currentuser))
                os.environ['HOSTNAME'] = currentuser
            elif not self.overuser:
                assert currentuser == user, 'Current User must be {0}'.format(user)
            else:
                print('Cannot override user.  Could not find current user')

