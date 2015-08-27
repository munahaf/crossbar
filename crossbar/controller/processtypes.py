#####################################################################################
#
#  Copyright (C) Tavendo GmbH
#
#  Unless a separate license agreement exists between you and Tavendo GmbH (e.g. you
#  have purchased a commercial license), the license terms below apply.
#
#  Should you enter into a separate license agreement after having received a copy of
#  this software, then the terms of such license agreement replace the terms below at
#  the time at which such license agreement becomes effective.
#
#  In case a separate license agreement ends, and such agreement ends without being
#  replaced by another separate license agreement, the license terms below apply
#  from the time at which said agreement ends.
#
#  LICENSE TERMS
#
#  This program is free software: you can redistribute it and/or modify it under the
#  terms of the GNU Affero General Public License, version 3, as published by the
#  Free Software Foundation. This program is distributed in the hope that it will be
#  useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
#
#  See the GNU Affero General Public License Version 3 for more details.
#
#  You should have received a copy of the GNU Affero General Public license along
#  with this program. If not, see <http://www.gnu.org/licenses/agpl-3.0.en.html>.
#
#####################################################################################

from __future__ import absolute_import, print_function

import os
import six
import json

from collections import deque

from datetime import datetime

from twisted.internet.defer import Deferred

from crossbar._logging import make_logger, LogLevel, record_separator
from crossbar._logging import cb_logging_aware, escape_formatting

__all__ = ('RouterWorkerProcess',
           'ContainerWorkerProcess',
           'GuestWorkerProcess')


class WorkerProcess(object):
    """
    Internal run-time representation of a worker process.
    """
    TYPE = 'worker'
    LOGNAME = 'Worker'

    def __init__(self, controller, id, who, keeplog=None):
        """
        Ctor.

        :param controller: The node controller this worker was created by.
        :type controller: instance of NodeControllerSession
        :param id: The ID of the worker.
        :type id: str
        :param who: Who triggered creation of this worker.
        :type who: str
        :param keeplog: If not `None`, buffer log message received to be later
                        retrieved via getlog(). If `0`, keep infinite log internally.
                        If `> 0`, keep at most such many log entries in buffer.
        :type keeplog: int or None
        """
        self._logger = make_logger()

        self._controller = controller

        self.id = id
        self.who = who
        self.pid = None
        self.status = "starting"

        self.created = datetime.utcnow()
        self.connected = None
        self.started = None

        self._log_entries = deque(maxlen=10)

        self._log_fds = [1, 2]
        self._log_lineno = 0
        self._log_topic = 'crossbar.node.{}.worker.{}.on_log'.format(self._controller._node_id, self.id)

        self._log_rich = None  # Does not support rich logs

        # A deferred that resolves when the worker is ready.
        self.ready = Deferred()

        # A deferred that resolves when the worker has exited.
        self.exit = Deferred()
        self.exit.addBoth(self._dump_remaining_log)

    def getlog(self):
        return list(self._log_entries)

    def _dump_remaining_log(self, result):
        """
        If there's anything left in the log buffer, log it out so it's not
        lost.
        """
        if self._log_rich and self._log_data != u"":
            self._logger.warn("REMAINING LOG BUFFER AFTER EXIT FOR PID {pid}:",
                              pid=self.pid)

            for log in self._log_data.split(os.linesep):
                self._logger.warn(escape_formatting(log))

        return result

    def log(self, childFD, data):
        """
        Handle a log message (or a fragment of such) coming in.
        """
        assert(childFD in self._log_fds)

        system = "{:<10} {:>6}".format(self.LOGNAME, self.pid)

        if childFD == 1:
            # This is a log message made from some super dumb software that
            # writes directly to FD1 instead of sys.stdout (which is captured
            # by the logger). Because of this, we can't trust any portion of it
            # and repr() it.
            self._logger.info(repr(data), cb_namespace="FD1", log_system=system)
            self._log_entries.append(repr(data))
            return

        if type(data) != six.text_type:
            data = data.decode('utf8')

        if self._log_rich is None:
            # If it supports rich logging, it will print just the logger aware
            # "magic phrase" as its first message.
            if data[0:len(cb_logging_aware)] == cb_logging_aware:
                self._log_rich = True
                self._log_data = u""  # Log buffer
                return
            else:
                self._log_rich = False

        if self._log_rich:
            # This guest supports rich logs.
            self._log_data += data

            while record_separator in self._log_data:

                log, self._log_data = self._log_data.split(record_separator, 1)

                try:
                    event = json.loads(log)
                except ValueError:
                    # If invalid JSON is written out, just output the raw text.
                    # We tried!
                    event = {"level": u"warn",
                             "text": u"INVALID JSON: {}".format(escape_formatting(log))}
                event_text = event.pop("text")
                event_namespace = event.pop("namespace", None)
                level = LogLevel.levelWithName(event.pop("level"))

                self._logger.emit(level, event_text, log_system=system,
                                  cb_namespace=event_namespace, **event)
                self._log_entries.append(event)

                if self._log_topic:
                    self._controller.publish(self._log_topic, event_text)

        else:
            # Rich logs aren't supported
            data = escape_formatting(data)

            for row in data.split(os.linesep):
                row = row.strip()

                if row == u"":
                    continue

                self._logger.info(row, log_system=system)
                self._log_entries.append(row)

                if self._log_topic:
                    self._controller.publish(self._log_topic, row)


class NativeWorkerProcess(WorkerProcess):
    """
    Internal run-time representation of a native worker (router or
    container currently) process.
    """

    TYPE = 'native'
    LOGNAME = 'Native'

    def __init__(self, controller, id, who, keeplog=None):
        """
        Ctor.

        :param controller: The node controller this worker was created by.
        :type controller: instance of NodeControllerSession
        :param id: The ID of the worker.
        :type id: str
        :param who: Who triggered creation of this worker.
        :type who: str
        """
        WorkerProcess.__init__(self, controller, id, who, keeplog)

        self.factory = None
        self.proto = None


class RouterWorkerProcess(NativeWorkerProcess):
    """
    Internal run-time representation of a router worker process.
    """

    TYPE = 'router'
    LOGNAME = 'Router'


class ContainerWorkerProcess(NativeWorkerProcess):
    """
    Internal run-time representation of a container worker process.
    """

    TYPE = 'container'
    LOGNAME = 'Container'


class GuestWorkerProcess(WorkerProcess):
    """
    Internal run-time representation of a guest worker process.
    """

    TYPE = 'guest'
    LOGNAME = 'Guest'

    def __init__(self, controller, id, who, keeplog=None):
        """
        Ctor.

        :param controller: The node controller this worker was created by.
        :type controller: instance of NodeControllerSession
        :param id: The ID of the worker.
        :type id: str
        :param who: Who triggered creation of this worker.
        :type who: str
        """
        WorkerProcess.__init__(self, controller, id, who, keeplog)

        self._log_fds = [1, 2]
        self.proto = None
