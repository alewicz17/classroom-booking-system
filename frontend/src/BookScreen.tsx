import { useRef, useState, type FormEvent } from "react";
import { formatUtc, request, toUtcIso, type Booking, type Room } from "./api";

type Props = { userId: string; rooms: Room[] };

export default function BookScreen({ userId, rooms }: Props) {
  const [roomId, setRoomId] = useState(rooms[0]?.id ?? "");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [pending, setPending] = useState(false);
  const [confirmation, setConfirmation] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Kept across submits of the same values, so a retry after a lost response is
  // recognised by the API as the same attempt (spec 004).
  const idempotencyKey = useRef<string | null>(null);

  function change(setter: (value: string) => void, value: string) {
    idempotencyKey.current = null;
    setter(value);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    idempotencyKey.current ??= crypto.randomUUID();
    setPending(true);
    setConfirmation(null);
    setError(null);
    try {
      const booking = await request<Booking>(userId, "/bookings", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey.current },
        body: { room_id: roomId, start: toUtcIso(start), end: toUtcIso(end) },
      });
      const room = rooms.find((r) => r.id === booking.room_id)?.name ?? booking.room_id;
      setConfirmation(
        `Booking confirmed: ${room}, ${formatUtc(booking.start)} – ${formatUtc(booking.end)}`,
      );
      idempotencyKey.current = null;
      setRoomId(rooms[0]?.id ?? "");
      setStart("");
      setEnd("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit}>
      <h2>Book a room</h2>
      <div className="booking-form__fields">
        <div className="field">
          <label htmlFor="room">Room</label>
          <select id="room" value={roomId} onChange={(e) => change(setRoomId, e.target.value)}>
            {rooms.map((room) => (
              <option key={room.id} value={room.id}>
                {room.name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="start">Start (UTC)</label>
          <input
            id="start"
            type="datetime-local"
            required
            value={start}
            onChange={(e) => change(setStart, e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="end">End (UTC)</label>
          <input
            id="end"
            type="datetime-local"
            required
            value={end}
            onChange={(e) => change(setEnd, e.target.value)}
          />
        </div>
      </div>
      <button type="submit" className="button" disabled={pending}>
        Book
      </button>
      {confirmation && <p className="message message--success">{confirmation}</p>}
      {error && (
        <p role="alert" className="message message--error">
          {error}
        </p>
      )}
    </form>
  );
}
