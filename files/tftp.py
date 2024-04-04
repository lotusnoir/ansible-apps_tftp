from fbtftp.base_handler import BaseHandler
from fbtftp.base_handler import ResponseData
from fbtftp.base_server import BaseServer
import os
from argparse import ArgumentParser
import requests
import logging
from logging.handlers import RotatingFileHandler


def print_session_stats(stats):
    '''
    logging.info("Stats: for %r requesting %r" % (stats.peer, stats.file_path))
    logging.info("Error: %r" % stats.error)
    logging.info("Time spent: %dms" % (stats.duration() * 1e3))
    logging.info("Packets sent: %d" % stats.packets_sent)
    logging.info("Packets ACKed: %d" % stats.packets_acked)
    logging.info("Bytes sent: %d" % stats.bytes_sent)
    logging.info("Options: %r" % stats.options)
    logging.info("Blksize: %r" % stats.blksize)
    logging.info("Retransmits: %d" % stats.retransmits)
    logging.info("Server port: %d" % stats.server_addr[1])
    logging.info("Client port: %d" % stats.peer[1])
    '''
    logging.info('{ peer: "%r", file_path: "%r", error: "%r", duration: "%dms", pkts_sent: "%d", pkts_acked "%d", bytes_sent: "%d", options: "%r", blksize: "%r", retransmits: "%d", srv_port: "%d", client_port: "%d" }' % (stats.peer, stats.file_path, stats.error, (stats.duration() * 1e3), stats.packets_sent, stats.packets_acked, stats.bytes_sent, stats.options, stats.blksize, stats.retransmits, stats.server_addr[1], stats.peer[1]))


def print_server_stats(stats):
    counters = stats.get_and_reset_all_counters()
    if "process_count" in counters:
        logging.info("Number of spawned TFTP workers in the last %d seconds : %d"
                     % (stats.interval, counters["process_count"]))


class FileResponseData(ResponseData):
    '''
    Class representing a TFTP response when using the filesystem backend
    '''
    def __init__(self, path):
        self._size = os.stat(path).st_size
        self._reader = open(path, 'rb')

    def read(self, n):
        return self._reader.read(n)

    def size(self):
        return self._size

    def close(self):
        self._reader.close()


class FileHandler(BaseHandler):
    '''
    A class instanciated when we get a request, if using the filesystem backend
    '''
    def __init__(self, server_addr, peer, path, options, root, stats_callback):
        self._root = root  # The root directory where we will look for files
        super().__init__(server_addr, peer, path, options, stats_callback)

    def get_response_data(self):
        return FileResponseData(os.path.join(self._root, self._path))


class HTTPResponseData(ResponseData):
    '''
    Class representing a TFTP response when using the HTTP backend
    '''
    def __init__(self, path, peer_ip):
        self._request = requests.get(path, stream=True, headers={"X-Forwarded-For": peer_ip})  # Start requesting the actual file from the HTTP server while providing the actual client IP as a header
        self._request.raise_for_status()
        logging.debug('HTTP response headers : %r' % self._request.headers)
        self._size = self._request.headers['Content-length']  # At this point we have'nt downloaded the full content but we still need to know the size, so we trust this response header

    def read(self, n):
        return self._request.raw.read(n)  # Download the actual content

    def size(self):
        return self._size

    def close(self):
        pass


class HTTPHandler(BaseHandler):
    '''
    A class instanciated when we get a request, if using the HTTP backend
    '''
    def __init__(self, server_addr, peer, path, options, root, stats_callback):
        self._root = root  # The base URL
        self._peer_ip = peer[0]  # peer is a tuple of the following form : ('127.0.0.1', 35457). But we only need to provide the client IP
        super().__init__(server_addr, peer, path, options, stats_callback)

    def get_response_data(self):
        return HTTPResponseData(self._root + self._path, self._peer_ip)


class TFTPServer(BaseServer):
    '''
    The base class of our TFTP server
    '''
    def __init__(self, address, port, retries, timeout, backend, root,
                 handler_stats_callback, server_stats_callback=None):
        self._backend = backend  # Serve files from local filesystem, or proxy to a HTTP server
        self._root = root  # This will be 'prefixed' to the requested file : the TFTP root dir for filesystem, or base URL for HTTP
        self._handler_stats_callback = handler_stats_callback
        super().__init__(address, port, retries, timeout, server_stats_callback)

    def get_handler(self, server_addr, peer, path, options):
        if self._backend == 'file':
            return FileHandler(server_addr, peer, path, options, self._root,
                                 self._handler_stats_callback)
        elif self._backend == 'http':
            return HTTPHandler(server_addr, peer, path, options, self._root,
                                 self._handler_stats_callback)
        else:
            raise ValueError('Unknown backend : %s' % self._backend)


def main(backend='static', root='/tftproot', address='0.0.0.0', port=1069, debug=False):
    try:
        if debug:
            logging.getLogger().setLevel(logging.DEBUG)
        else:
            #logging.getLogger().setLevel(logging.INFO)
            logging.getLogger().setLevel(logging.INFO)
        logging.getLogger().addHandler(RotatingFileHandler("/var/log/tftp.log"))
        logging.info('Starting TFTP server with backend %s (on %s), listening on %s:%d' % (
                     backend, root, address, port))
        server = TFTPServer(address=address, port=port, retries=3, timeout=5,
                            backend=backend, root=root, handler_stats_callback=print_session_stats,
                            server_stats_callback=print_server_stats)

        try:
            server.run()
        except KeyboardInterrupt:
            server.close()
    except Exception:
        logging.getLogger().exception("Error")
        raise

if __name__ == '__main__':
    parser = ArgumentParser(description='Run a simple TFTP server.')
    parser.add_argument('-b', '--backend', choices=['file', 'http'], default='file', help='Backend to fetch files from')
    parser.add_argument('-r', '--root', help='Base where to fetch files from (directory or URL)')
    parser.add_argument('-a', '--address', default='0.0.0.0', help='IP address to listen on')
    parser.add_argument('-p', '--port', default=69, type=int, help='UDP port to listen on')
    parser.add_argument('-d', '--debug', action='store_true', help='Enable debug output')
    args = parser.parse_args()
    main(args.backend, args.root, args.address, args.port, args.debug)
