#!/usr/bin/env python3

"""Simple test web server for demonstrating VPC connectivity."""
from http.server import HTTPServer, SimpleHTTPRequestHandler
import sys

def main():
    if len(sys.argv) != 2:
        print("Usage: python web_server.py <port>")
        sys.exit(1)

    port = int(sys.argv[1])
    server_address = ('', port)
    httpd = HTTPServer(server_address, SimpleHTTPRequestHandler)
    print(f'Starting web server on port {port}...')
    httpd.serve_forever()

if __name__ == '__main__':
    main()