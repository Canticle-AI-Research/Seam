import React from 'react';
import './index.css';

const DASHBOARD_URL = '/dashboard.html';

export default function App() {
  const [failed, setFailed] = React.useState(false);

  if (failed) {
    return (
      <main className="prototype-fallback">
        <h1>SEAM dashboard prototype is unavailable</h1>
        <p>
          Vite should be serving the finished dashboard from
          <code> experimental/webui/public/dashboard.html</code>.
        </p>
      </main>
    );
  }

  return (
    <iframe
      className="prototype-frame"
      src={DASHBOARD_URL}
      title="SEAM dashboard"
      onError={() => setFailed(true)}
    />
  );
}
