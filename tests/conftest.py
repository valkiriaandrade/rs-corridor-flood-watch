"""Shared test fixtures."""

import socket

import pytest

LOCAL = {'127.0.0.1', '::1', 'localhost'}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never download anything (Open-Meteo, MERGE, S2iD): fail loudly on any connection attempt.

    Loopback stays open: the event loop behind Streamlit's AppTest uses a local socket pair on Windows."""
    connect, create_connection = socket.socket.connect, socket.create_connection

    def _check(address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in LOCAL:
            raise RuntimeError(f'Tests must not use the network ({host}); use the committed files or a fake response')

    def guarded_connect(self, address):
        _check(address)
        return connect(self, address)

    def guarded_create_connection(address, *args, **kwargs):
        _check(address)
        return create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, 'connect', guarded_connect)
    monkeypatch.setattr(socket, 'create_connection', guarded_create_connection)
