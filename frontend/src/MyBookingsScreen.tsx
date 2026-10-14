import { useCallback, useEffect, useState } from "react";
import { formatUtc, request, type Booking, type Room } from "./api";

type Props = { userId: string; rooms: Room[] };

export default function MyBookingsScreen({ userId, rooms }: Props) {
  const [bookings, setBookings] = useState<Booking[] | null>(null);
  const [cancelling, setCancelling] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      request<Booking[]>(userId, "/bookings")
        .then(setBookings)
        .catch((e: Error) => setError(e.message)),
    [userId],
  );

  useEffect(() => {
    load();
  }, [load]);

  async function cancel(bookingId: string) {
    setCancelling(bookingId);
    setError(null);
    try {
      await request<Booking>(userId, `/bookings/${bookingId}/cancel`, { method: "POST" });
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setCancelling(null);
    }
  }

  const roomName = (roomId: string) => rooms.find((r) => r.id === roomId)?.name ?? roomId;

  return (
    <section>
      <h2>My bookings</h2>
      {error && (
        <p role="alert" className="message message--error">
          {error}
        </p>
      )}
      {bookings?.length === 0 && <p className="empty">No bookings yet.</p>}
      {bookings && bookings.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Room</th>
                <th>Start</th>
                <th>End</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {bookings.map((booking) => (
                <tr key={booking.id} className={`row--${booking.status}`}>
                  <td>{roomName(booking.room_id)}</td>
                  <td>{formatUtc(booking.start)}</td>
                  <td>{formatUtc(booking.end)}</td>
                  <td>
                    <span className={`status status--${booking.status}`}>{booking.status}</span>
                  </td>
                  <td>
                    {booking.status === "confirmed" && (
                      <button
                        className="button button--quiet"
                        disabled={cancelling === booking.id}
                        onClick={() => cancel(booking.id)}
                      >
                        Cancel
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
