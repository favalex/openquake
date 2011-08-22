# -*- coding: utf-8 -*-

# Copyright (c) 2010-2011, GEM Foundation.
#
# OpenQuake is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License version 3
# only, as published by the Free Software Foundation.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License version 3 for more details
# (a copy is included in the LICENSE file that accompanied this code).
#
# You should have received a copy of the GNU Lesser General Public License
# version 3 along with OpenQuake.  If not, see
# <http://www.gnu.org/licenses/lgpl-3.0.txt> for a copy of the LGPLv3 License.


"""
Classes dealing with amqp signalling between jobbers, workers and supervisors.
"""
import time

from amqplib import client_0_8 as amqp

from openquake.utils import config


class LogMessageConsumer(object):
    """
    A class to consume logging messages generated by an OpenQuake job.

    Typical use:

        class MyConsumer(LogMessageConsumer):
            def message_callback(self, msg):
                pass

        with MyConsumer(job_id) as mc:
            mc.run()
    """
    def __init__(self, job_id, levels=None, timeout=None):
        """
        :param job_id: the id of the job whose logging messages we are
                       interested in
        :type job_id: int
        :param levels: the logging levels we are interested in
        :type levels: None for all the levels (translated to a '*' in the
                      routing_key) or an iterable of stings
                      (e.g. ['ERROR', 'CRITICAL'])
        :param timeout: the optional timeout in seconds. When it expires the
                        `timeout_callback` will be called.
        :type timeout: None or float
        """

        self.timeout = timeout

        cfg = config.get_section("amqp")

        self.conn = amqp.Connection(host=cfg['host'],
                                    userid=cfg['user'],
                                    password=cfg['password'],
                                    virtual_host=cfg['vhost'])
        self.chn = self.conn.channel()
        # I use the vhost as a realm, which seems to be an arbitrary string
        self.chn.access_request(cfg['vhost'], active=False, read=True)
        self.chn.exchange_declare(cfg['exchange'], 'topic', auto_delete=True)

        self.qname = 'supervisor-%s' % job_id
        self.chn.queue_declare(self.qname)

        if levels is None:
            levels = ('*',)

        for level in levels:
            self.chn.queue_bind(self.qname, cfg['exchange'],
                               routing_key='log.%s.%s' % (level, job_id))

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.chn.close()
        self.conn.close()

    def run(self):
        """
        Run the loop waiting for messages or timeout expiration and calling the
        appropriate callback.

        The callbacks can stop the loop by raising StopIteration.
        """

        if self.timeout:
            # Resort to polling when a timeout is specified, because of
            # limitations of the amqplib API.
            while True:
                time.sleep(self.timeout)

                try:
                    self.timeout_callback()
                except StopIteration:
                    break

                msg = self.chn.basic_get(self.qname)
                if msg:
                    try:
                        self.message_callback(msg)
                    except StopIteration:
                        self.chn.basic_ack(msg.delivery_tag)
                        break
                    else:
                        self.chn.basic_ack(msg.delivery_tag)
        else:
            tag = self.chn.basic_consume(self.qname,
                                         callback=self.message_callback)

            while self.chn.callbacks:
                try:
                    self.chn.wait()
                except StopIteration:
                    # this will remove the callback from self.chn.callbacks
                    self.chn.basic_cancel(tag)

    def message_callback(self, msg):  # pylint: disable=W0613,R0201
        """
        Called by `run` when a message is received.

        Can raise StopIteration to stop the loop inside `run` and let it return
        to the caller.
        """
        pass

    def timeout_callback(self):  # pylint: disable=R0201
        """
        Called by `run` each time the timeout expires.

        Can raise StopIteration to stop the loop inside `run` and let it return
        to the caller.
        """
        pass