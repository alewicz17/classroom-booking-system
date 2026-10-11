import { useEffect, useState } from "react";

export default function App() {
  const [apiStatus, setApiStatus] = useState("checking...");

  useEffect(() => {
    fetch("/api/health")
      .then((response) => (response.ok ? response.json() : Promise.reject(response.status)))
      .then((body: { status: string }) => setApiStatus(body.status))
      .catch(() => setApiStatus("unreachable"));
  }, []);

  return (
    <main>
      <h1>Classroom Booking</h1>
      <p>API: {apiStatus}</p>
    </main>
  );
}
