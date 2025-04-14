# coding=utf-8
from __future__ import unicode_literals

from pyFG.forticonfig import FortiConfig

from netmiko import ConnectHandler

import re
import os
import io
from difflib import Differ

import logging

logger = logging.getLogger('pyFG')


class FortiOS(object):

    def __init__(self, hostname, username, password, vdom=None, device_type='fortinet', timeout=60):
        """
        Represents a device running FortiOS.

        A :py:class:`FortiOS` object has three different :class:`~pyFG.forticonfig.FortiConfig` objects:

        * **running_config** -- You can populate this from the device or from a file with the\
            :func:`~pyFG.fortios.FortiOS.load_config` method. This will represent the live config\
            of the device and shall not be modified by any means as that might break other methods as the \
            :func:`~pyFG.fortios.FortiOS.commit`
        * **candidate_config** -- You can populate this using the same mechanisms as you would populate the\
            running_config. This represents the config you want to reach so, if you want to apply\
            changes, here is where you would apply them.
        * **original_config** -- This is automatically populated when you do a commit with the original config\
            prior to the commit. This is useful for the :func:`~pyFG.fortios.FortiOS.rollback` operation or for\
            checking stuff later on.

        Args:
            * **hostname** (str) -- FQDN or IP of the device you want to connect.
            * **vdom** (str) -- VDOM you want to connect to. If it is None we will run the commands without moving\
                to a VDOM.
            * **username** (str) -- Username to connect to the device. If none is specified the current user will be\
                used
            * **password** (str) -- Username password
            * **keyfile** (str) -- Path to the private key in case you want to use this authentication method.
            * **timeout** (int) -- Time in seconds to wait for the device to respond.

        """
        self.host = host
        self.vdom = vdom
        self.original_config = None
        self.running_config = FortiConfig('running', vdom=vdom)
        self.candidate_config = FortiConfig('candidate', vdom=vdom)
        self.ssh = None
        self.username = username
        self.password = password
        self.device_type = device_type
        self.timeout = timeout
        
    def open(self):
        """
        Opens the ssh session with the device.
        """

        logger.debug(f'Connecting to device {self.host}')

        cfg = {
            'device_type': self.device_type,
            'host': self.host,
            'username': self.username,
            'password': self.password,
        }

        self.ssh = ConnectHandler(**cfg)

    def close(self):
        """
        Closes the ssh session with the device.
        """

        logger.debug(f'Closing connection to device {self.host}')
        self.ssh.close()

    def execute_command(self, command):
        """
        This method will execute the commands on the device without as if you were just connected to it (it will not
        enter into any vdom). This method is not recommended unless you are 100% sure of what you are doing.


        Args:
            * **command** (str) -- Command to execute.

        Returns:
            A list of strings containing the output.

        Raises:
            exceptions.CommandExecutionException -- If it detects any problem with the command.
        """
        logger.debug(f'Executing commands:\n {command}')

        err_msg = 'Something happened when executing some commands on device'

        output = self.ssh.send_command(command)

        regex = re.compile('Command fail')
        if len(regex.findall(output)) > 0:
            msg = f'{err_msg}:\n{command}\n{output}'
            logger.error(msg)
            raise exceptions.CommandExecutionException(msg)

        output = output.splitlines()

        return output

    def load_config(self, path='', in_candidate=False, empty_candidate=False, config_text=None):
        """
        This method will load a block of config represented as a :py:class:`FortiConfig` object in the running
        config, in the candidate config or in both.

        Args:
            * **path** (str) -- This is the block of config you want to load. For example *system interface*\
                or *router bgp*
            * **in_candidate** (bool):
                * If ``True`` the config will be loaded as *candidate*
                * If ``False`` the config will be loaded as *running*
            * **empty_candidate** (bool):
                * If ``True`` the *candidate* config will be left unmodified.
                * If ``False`` the *candidate* config will be loaded with a block of config containing\
                the same information as the config loaded in the *running* config.
            * **config_text** (str) -- Instead of loading the config from the device itself (using the ``path``\
                variable, you can specify here the config as text.
        """
        logger.info('Loading config. path:%s, in_candidate:%s, empty_candidate:%s, config_text:%s' % (
            path, in_candidate, empty_candidate, config_text is not None))

        if config_text is None:
            if self.vdom is not None:
                if self.vdom == 'global':
                    command = f'conf global\nshow {path}\nend'
                else:
                    command = f'conf vdom\nedit {self.vdom}\nshow {path}\nend'
            else:
                command = f'show {path}'

            config_text = self.execute_command(command)

        if not in_candidate:
            self.running_config.parse_config_output(config_text)
            self.running_config.add_path(path)

        if not empty_candidate or in_candidate:
            self.candidate_config.parse_config_output(config_text)
            self.candidate_config.add_path(path)

    def compare_config(self, other=None, text=False):
        """
        Compares running config with another config. This other config can be either the *running*
        config or a :class:`~pyFG.forticonfig.FortiConfig`. The result of the comparison will be how to reach\
        the state represented in the target config (either the *candidate* or *other*) from the *running*\
        config.

        Args:
            * **other** (:class:`~pyFG.forticonfig.FortiConfig`) -- This parameter, if specified, will be used for the\
                comparison. If it is not specified the candidate config will be used.
            * **text** (bool):
                * If ``True`` this method will return a text diff showing how to get from the running config to\
                    the target config.
                * If ``False`` this method will return all the exact commands that needs to be run on the running\
                    config to reach the target config.

        Returns:
            See the explanation of the *text* arg in the section Args.

        """
        if other is None:
            other = self.candidate_config

        if not text:
            return self.running_config.compare_config(other)
        else:
            diff = Differ()
            result = diff.compare(
                self.running_config.to_text().splitlines(),
                other.to_text().splitlines()
            )
            return '\n'.join(result)

    def commit(self, config_text=None, force=False):
        """
        This method will push some config changes to the device. If the commit is successful the running
        config will be updated from the device and the previous config will be stored in the
        original config. The candidate config will not be updated. If the commit was successful it should
        match the running config. If it was not successful it will most certainly be different.

        Args:
            * **config_text** (string) -- If specified these are the config changes that will be applied. If you\
                don't specify this parameter it will execute all necessary commands to reach the candidate_config from\
                the running config.
            * **force(bool)**:
                * If ``True`` the new config will be pushed in *best effort*, errors will be ignored.
                * If ``False`` a rollback will be triggered if an error is detected

        Raises:
            * :class:`~pyFG.exceptions.FailedCommit` -- Something failed but we could rollback our changes
            * :class:`~pyFG.exceptions.ForcedCommit` -- Something failed but we avoided any rollback
        """
        self._commit(config_text, force)

    def _commit(self, config_text=None, force=False, reload_original_config=True):
        """
        This method is the same as the :py:method:`commit`: method, however, it has an extra command that will trigger
        the reload of the running config. The reason behind this is that in some circumstances you don´ want
        to reload the running config, for example, when doing a rollback.

        See :py:method:`commit`: for more details.
        """
        def _execute(config_text):
            if config_text is None:
                config_text = self.compare_config()

            config_vdom = ""

            if self.vdom is None:
                pre = ''
            elif not 'global' in self.vdom:
                config_vdom = f'conf vdom\n  edit {self.vdom}\n'
                pre = 'conf global\n    '
            else:
                pre = 'conf global\n    '

            cmd = f'{pre}execute batch start\n'
            cmd += config_vdom
            cmd += config_text
            cmd += '\nexecute batch end\n'

            self.execute_command(cmd)
            last_log = self.execute_command(f'{pre}execute batch lastlog')

            return self._parse_batch_lastlog(last_log)

        logger.info('Committing config ')

        wrong_commands = _execute(config_text)

        self._reload_config(reload_original_config)

        retry_codes = [-3, -23]
        retries = 5
        while retries > 0:
            retries -= 1
            for wc in wrong_commands:
                if int(wc[0]) in retry_codes:
                    if config_text is None:
                        config_text = self.compare_config()
                    wrong_commands = _execute(config_text)
                    self._reload_config(reload_original_config=False)
                    break

        if len(wrong_commands) > 0:
            exit_code = -2
            logging.debug(f'List of commands that failed: {wrong_commands}')

            if not force:
                exit_code = -1
                self.rollback()

            if exit_code < 0:
                raise exceptions.FailedCommit(wrong_commands)

    def rollback(self):
        """
        It will rollback all changes and go to the *original_config*
        """
        logger.info('Rolling back changes')

        config_text = self.compare_config(other=self.original_config)

        if len(config_text) > 0:
            return self._commit(config_text, force=True, reload_original_config=False)

    @staticmethod
    def _parse_batch_lastlog(last_log):
        """
        This static method will help reading the result of the commit, command by command.

        Args:
            last_log(list): A list containing, line by line, the result of committing the changes.

        Returns:
            A list of tuples that went wrong. The tuple will contain (*status_code*, *command*)
        """
        regexp = re.compile('(-?[0-9]\d*):\W+(.*)')

        wrong_commands = list()
        for line in last_log:
            result = regexp.match(line)
            if result is not None:
                status_code = result.group(1)
                command = result.group(2)
                if int(status_code) < 0:
                    wrong_commands.append((status_code, command))

        return wrong_commands

    def _reload_config(self, reload_original_config):
        """
        This command will update the running config from the live device.

        Args:
            * reload_original_config:
                * If ``True`` the original config will be loaded with the running config before reloading the\
                original config.
                * If ``False`` the original config will remain untouched.
        """
        # We don't want to reload the config under some circumstances
        if reload_original_config:
            self.original_config = self.running_config
            self.original_config.set_name('original')

        paths = self.running_config.get_paths()

        self.running_config = FortiConfig('running', vdom=self.vdom)

        for path in paths:
            self.load_config(path, empty_candidate=True)
