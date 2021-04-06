##############################################################################
#
#                        Crossbar.io FX
#     Copyright (C) Crossbar.io Technologies GmbH. All rights reserved.
#
##############################################################################

import os
from copy import deepcopy
from pprint import pformat

from twisted.internet.defer import inlineCallbacks
from twisted.web import server
from twisted.web.resource import Resource

import crossbar
from crossbar._util import hl
from crossbar.webservice.base import RouterWebService

from txaio import time_ns, make_logger

__all__ = ('RouterWebServiceRegisterMe', )


class RegisterMeResource(Resource):
    """
    Web resource to register master nodes with the XBR network.

    IMPORTANT: this resource is only indented to run inside master nodes!
    """
    log = make_logger()

    register_at = 'https://planet.xbr.network'

    def __init__(self, templates, worker, node_type=None):
        Resource.__init__(self)
        self._worker = worker
        self._service_realm = 'com.crossbario.fabric'
        self._service_agent = self._worker.realm_by_name(self._service_realm).session

        self._page = templates.get_template('registerme.html')
        self._pid = '{}'.format(os.getpid())
        self._node_type = node_type.strip().upper()

        assert self._node_type in ['MASTER']

    def _delayedRender(self, infos, request):
        try:
            peer = request.transport.getPeer()
            peer = '{}:{}'.format(peer.host, peer.port)
        except:
            peer = '?:?'

        kwargs = deepcopy(infos)

        node_time = time_ns()
        register_url = '{}/register-node?node_type={}&node_key={}&node_time={}'.format(
            self.register_at, self._node_type, kwargs['node_status']['pubkey'], node_time)

        kwargs['node_time'] = node_time
        kwargs['is_registered'] = False
        kwargs['cb_version'] = crossbar.__version__
        kwargs['worker_pid'] = self._pid
        kwargs['peer'] = peer
        kwargs['register_url'] = register_url
        kwargs['node_type'] = self._node_type

        s = self._page.render(**kwargs)
        request.write(s.encode('utf8'))
        request.finish()

    @inlineCallbacks
    def _do_get(self, request):
        try:
            node_status = yield self._worker.call('crossbar.get_status')
            master_status = yield self._service_agent.call('crossbarfabriccenter.domain.get_status')
            master_license = yield self._service_agent.call('crossbarfabriccenter.domain.get_license')
            master_version = yield self._service_agent.call('crossbarfabriccenter.domain.get_version')
            infos = {
                'node_status': node_status,
                'master_status': master_status,
                'master_license': master_license,
                'master_version': master_version,
            }
            self.log.debug('rendering {page} page using data\n{data}',
                           page=hl('register-master', bold=True),
                           data=pformat(infos))
            self._delayedRender(infos, request)
        except:
            self.log.failure()
            request.finish()

    def render_GET(self, request):
        self._do_get(request)
        return server.NOT_DONE_YET

    def getChild(self, path, request):
        self.log.debug(
            '{kass}.getChild(path={path}, request={request}, prepath={prepath}, postpath={postpath})',
            kass=self.__class__.__name__,
            path=path,
            prepath=request.prepath,
            postpath=request.postpath,
            request=request)

        search_path = b'/'.join([path] + request.postpath).decode('utf8')

        if search_path == '' or search_path.endswith('/') or search_path in ['register', 'register.html']:
            return self
        else:
            return Resource.getChild(self, path, request)


class RouterWebServiceRegisterMe(RouterWebService):
    """
    Crossbar.io FX "register-me" home page.

    IMPORTANT: this web service is only indented to run inside master nodes!
    """
    @staticmethod
    def check(personality, config):
        """
        Checks the configuration item. When errors are found, an
        InvalidConfigException exception is raised.

        :param personality: The node personality class.
        :param config: The Web service configuration item.
        :raises: crossbar.common.checkconfig.InvalidConfigException
        """
        pass

    @staticmethod
    def create(transport, path, config):
        personality = transport.worker.personality
        personality.WEB_SERVICE_CHECKERS['registerme'](personality, config)

        resource = RegisterMeResource(transport.templates, transport.worker, node_type=personality.NAME)

        return RouterWebServiceRegisterMe(transport, path, config, resource)
