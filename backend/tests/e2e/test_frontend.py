from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from playwright.sync_api import Locator, Page, Route, expect

from booking.domain.booking import Booking

GivenBooking = Callable[..., Booking]

# The spec's separator in "Booking confirmed"; escaped because ruff flags it as ambiguous.
EN_DASH = "\u2013"

# The header and the form both have a "Book" button, so locators are scoped to one of them.


def header(page: Page) -> Locator:
    return page.get_by_role("banner")


def main(page: Page) -> Locator:
    return page.get_by_role("main")


def oct_(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=UTC)


def fill_booking_form(page: Page, room: str, start: str, end: str) -> None:
    page.get_by_label("Room", exact=True).select_option(label=room)
    page.get_by_label("Start (UTC)").fill(start)
    page.get_by_label("End (UTC)").fill(end)


def booking_rows(page: Page, start: str) -> Locator:
    """The rows of the My bookings table whose Start column shows the given time."""
    return (
        main(page).get_by_role("row").filter(has=page.get_by_role("cell", name=start, exact=True))
    )


def expect_booking_row(row: Locator, room: str, start: str, end: str, status: str) -> None:
    cells = row.get_by_role("cell")
    expect(cells.nth(0)).to_have_text(room)
    expect(cells.nth(1)).to_have_text(start)
    expect(cells.nth(2)).to_have_text(end)
    expect(cells.nth(3)).to_have_text(status)


def test_user_books_a_room(page: Page) -> None:
    page.goto("/")

    fill_booking_form(page, "Room 1", "2026-10-22T08:00", "2026-10-22T09:00")
    main(page).get_by_role("button", name="Book", exact=True).click()

    expect(
        page.get_by_text(
            f"Booking confirmed: Room 1, 2026-10-22 08:00 UTC {EN_DASH} 2026-10-22 09:00 UTC"
        )
    ).to_be_visible()
    header(page).get_by_role("button", name="My bookings").click()
    row = booking_rows(page, "2026-10-22 08:00 UTC")
    expect(row).to_have_count(1)
    expect_booking_row(row, "Room 1", "2026-10-22 08:00 UTC", "2026-10-22 09:00 UTC", "confirmed")
    expect(row.get_by_role("button", name="Cancel")).to_be_visible()


def test_user_cancels_a_booking(
    page: Page, given_booking: GivenBooking, user_a: UUID, room_1: UUID
) -> None:
    given_booking(room_1, user_a, oct_(22, 8), oct_(22, 9))
    page.goto("/")

    header(page).get_by_role("button", name="My bookings").click()
    row = booking_rows(page, "2026-10-22 08:00 UTC")
    row.get_by_role("button", name="Cancel").click()

    expect_booking_row(row, "Room 1", "2026-10-22 08:00 UTC", "2026-10-22 09:00 UTC", "cancelled")
    expect(row.get_by_role("button", name="Cancel")).to_have_count(0)


def test_taken_slot_shows_api_error(
    page: Page, given_booking: GivenBooking, user_b: UUID, room_1: UUID
) -> None:
    given_booking(room_1, user_b, oct_(22, 8), oct_(22, 9))
    page.goto("/")

    fill_booking_form(page, "Room 1", "2026-10-22T08:30", "2026-10-22T09:30")
    main(page).get_by_role("button", name="Book", exact=True).click()

    # The title of the 409 Problem Details response for SlotUnavailable.
    expect(page.get_by_role("alert")).to_contain_text("Slot unavailable")
    room = page.get_by_label("Room", exact=True)
    expect(room.locator("option:checked")).to_have_text("Room 1")
    expect(page.get_by_label("Start (UTC)")).to_have_value("2026-10-22T08:30")
    expect(page.get_by_label("End (UTC)")).to_have_value("2026-10-22T09:30")


def test_retry_after_lost_response_does_not_book_twice(page: Page) -> None:
    dropped: list[Route] = []

    def drop_first_post_response(route: Route) -> None:
        if route.request.method == "POST" and not dropped:
            dropped.append(route)
            route.fetch()  # the API handles the request and creates the booking
            route.abort()  # but the browser never sees the response
        else:
            route.continue_()

    page.route("**/api/bookings", drop_first_post_response)
    page.goto("/")

    fill_booking_form(page, "Room 1", "2026-10-22T08:00", "2026-10-22T09:00")
    book = main(page).get_by_role("button", name="Book", exact=True)
    book.click()
    expect(page.get_by_role("alert")).to_have_text("Could not reach the server. Try again.")
    book.click()

    expect(page.get_by_text("Booking confirmed")).to_be_visible()
    header(page).get_by_role("button", name="My bookings").click()
    expect(booking_rows(page, "2026-10-22 08:00 UTC")).to_have_count(1)
