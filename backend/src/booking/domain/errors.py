class SlotUnavailable(Exception):
    """The room already has a confirmed booking that overlaps the requested range."""
