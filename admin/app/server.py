import os
import ssl
import sys

from cheroot import wsgi
from cheroot.ssl.builtin import BuiltinSSLAdapter

from app import EXPOSED, app

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
    server = wsgi.Server(("0.0.0.0", 8444), app, numthreads=4)
    if EXPOSED:
        if not (os.path.exists(CERT) and os.path.exists(KEY)):
            sys.exit("The GUI is exposed (ADMIN_GUI_LISTEN is not 127.0.0.1) "
                     "but data/cert.pem or data/key.pem is missing.")
        server.ssl_adapter = tls_adapter()
        print("Exposed mode: HTTPS on port 8444, login required.", flush=True)
    else:
        print("Localhost mode: HTTP on port 8444, no login.", flush=True)
    try:
        server.start()
    except KeyboardInterrupt:
        server.stop()


if __name__ == "__main__":
    main()
