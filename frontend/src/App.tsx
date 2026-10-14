import { useEffect, useState } from "react";
import { request, USERS, type Room } from "./api";
import BookScreen from "./BookScreen";
import MyBookingsScreen from "./MyBookingsScreen";

type Screen = "book" | "my-bookings";

export default function App() {
  const [userId, setUserId] = useState(USERS[0].id);
  const [screen, setScreen] = useState<Screen>("book");
  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // Ignores the answer of a request made for a user who is no longer selected.
    let current = true;
    setRooms(null);
    setError(null);
    request<Room[]>(userId, "/rooms")
      .then((loaded) => current && setRooms(loaded))
      .catch((e: Error) => current && setError(e.message));
    return () => {
      current = false;
    };
  }, [userId]);

  return (
    <>
      <header className="site-header">
        <div className="site-header__inner">
          <div className="site-header__top">
            <h1>Classroom Booking</h1>
            <div className="acting-as">
              <label htmlFor="acting-as">Acting as</label>
              <select id="acting-as" value={userId} onChange={(e) => setUserId(e.target.value)}>
                {USERS.map((user) => (
                  <option key={user.id} value={user.id}>
                    {user.name}
                  </option>
                ))}
              </select>
            </div>
          </div>
          <nav className="tabs">
            <button
              className="tab"
              aria-current={screen === "book" ? "page" : undefined}
              onClick={() => setScreen("book")}
            >
              Book
            </button>
            <button
              className="tab"
              aria-current={screen === "my-bookings" ? "page" : undefined}
              onClick={() => setScreen("my-bookings")}
            >
              My bookings
            </button>
          </nav>
        </div>
      </header>
      <main className="page">
        {error && (
          <p role="alert" className="message message--error">
            {error}
          </p>
        )}
        {/* Keyed by user, so changing user remounts the screen: data reloads, messages clear. */}
        {rooms &&
          (screen === "book" ? (
            <BookScreen key={userId} userId={userId} rooms={rooms} />
          ) : (
            <MyBookingsScreen key={userId} userId={userId} rooms={rooms} />
          ))}
      </main>
    </>
  );
}
