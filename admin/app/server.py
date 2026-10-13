import os
import ssl
import sys

from cheroot import wsgi
from cheroot.ssl.builtin import BuiltinSSLAdapter

from app import EXPOSED, GATEWAY, PREFIX, SUBNETS, application

CERT = "/galene/data/cert.pem"
KEY = "/galene/data/key.pem"


def tls_adapter():
    """TLS with Galene's certificate, reloaded when the files change."""
    adapter = BuiltinSSLAdapter(CERT, KEY)
    current = {"mtime": os.stat(CERT).st_mtime, "context": adapter.context}

    def reload(sock, server_name, context):
        try:
            mtime = os.stat(CERT).st_mtime
            if mtime != current["mtime"]:
                new = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
                new.load_cert_chain(CERT, KEY)
                current.update(mtime=mtime, context=new)
                print("Reloaded the TLS certificate.", flush=True)
        except (OSError, ssl.SSLError) as e:
            print(f"Could not reload the TLS certificate: {e}", flush=True)
        if current["context"] is not context:
            sock.context = current["context"]

    adapter.context.sni_callback = reload
    return adapter


def main():
    server = wsgi.Server(("0.0.0.0", 8444), application, numthreads=4)
    if EXPOSED:
        if not (os.path.exists(CERT) and os.path.exists(KEY)):
            sys.exit("ADMIN_GUI_MODE is 'internet' "
                     "but data/cert.pem or data/key.pem is missing.")
        server.ssl_adapter = tls_adapter()
        print("Internet mode: HTTPS on port 8444, login required.",
              flush=True)
    else:
        print("LAN mode: HTTP on port 8444, no login, clients from "
              + ", ".join(str(n) for n in SUBNETS)
              + (f" and {GATEWAY} (this server)" if GATEWAY else "") + ".",
              flush=True)
    if PREFIX:
        print("Serving under the path prefix set in ADMIN_GUI_PATH.",
              flush=True)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
