"""Shared test fixtures."""
import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests never download anything (Open-Meteo, MERGE, S2iD): fail loudly on any connection attempt."""
    def guard(*args, **kwargs):
        raise RuntimeError('Tests must not use the network; use the committed files or a fake response')
    monkeypatch.setattr(socket.socket, 'connect', guard)
    monkeypatch.setattr(socket, 'create_connection', guard)
