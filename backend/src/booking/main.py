"""Composition root: wires adapters to services by hand."""

from booking.adapters.api import create_app

app = create_app()
