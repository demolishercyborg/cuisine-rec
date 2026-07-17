import { useState, useEffect, useRef } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_BASE || "/api";

const PRESETS = [
  { id: "savory", label: "Savory & rich", hint: "umami, deep, satisfying" },
  { id: "crispy", label: "Fried & crispy", hint: "crunch, golden, indulgent" },
  { id: "fresh", label: "Fresh & light", hint: "bright, crisp, clean" },
  { id: "spicy", label: "Spicy & bold", hint: "heat, punch, fire" },
  { id: "comforting", label: "Warm & comforting", hint: "cozy, hearty" },
  { id: "brothy", label: "Brothy & slurpable", hint: "soup, noodles, steam" },
  { id: "sweet", label: "Sweet treat", hint: "dessert, pastry, sugar" },
  { id: "smoky", label: "Smoky & charred", hint: "grilled, bbq" },
];

const DIETARY = ["vegetarian", "vegan", "halal", "gluten-free"];
const PRICE = ["", "$", "$$", "$$$", "$$$$"];

// Backend compares this against each restaurant's local opening hours, so it must be
// wall-clock local time, not UTC — Date#toISOString() converts to UTC and would shift
// the hour, making open places look closed (or vice versa).
function localIso(d) {
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

const TEMP_PREFS = [
  { id: "heat", label: "Love the heat", hint: "always warm, rich, and hearty" },
  { id: "warm", label: "Lean warm", hint: "a little cozy goes a long way" },
  { id: "neutral", label: "Weather decides", hint: "match whatever it's like outside" },
  { id: "fresh", label: "Lean fresh", hint: "lighter is usually better" },
  { id: "cool", label: "Beat the heat", hint: "cold and refreshing, always" },
];

function App() {
  const [coords, setCoords] = useState(null);
  const [geoError, setGeoError] = useState("");
  const [selected, setSelected] = useState([]);
  const [craving, setCraving] = useState("");
  const [dietary, setDietary] = useState([]);
  const [openOnly, setOpenOnly] = useState(true);
  const [tempPref, setTempPref] = useState("neutral");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);
  const resultsRef = useRef(null);

  // Ask for location once on load.
  useEffect(() => {
    if (!navigator.geolocation) {
      setGeoError("Geolocation isn't available in this browser.");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => setCoords({ lat: pos.coords.latitude, lng: pos.coords.longitude }),
      () => setGeoError("Turn on location to get nearby picks."),
      { timeout: 8000 }
    );
  }, []);

  function togglePreset(id) {
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));
  }

  function toggleDiet(d) {
    setDietary((s) => (s.includes(d) ? s.filter((x) => x !== d) : [...s, d]));
  }

  const canSubmit = coords && (selected.length || craving.trim());

  async function getRecs() {
    if (!canSubmit) return;
    setLoading(true);
    setError("");
    setResult(null);
    const now = new Date();
    try {
      const tempHints = {
        heat:    " (I always want warm, rich, hearty food — lean heavily toward that even if the weather is mild)",
        warm:    " (I lean toward warmer, cozier food — nudge slightly heartier than the weather alone would suggest)",
        neutral: "",
        fresh:   " (I tend to prefer lighter, fresher food — nudge slightly cooler than the weather alone would suggest)",
        cool:    " (I always want something light, cold, or refreshing — lean toward that even if the weather is cool)",
      };
      const tempHint = tempHints[tempPref] ?? "";
      const presetDescriptions = selected.map((id) => {
        const p = PRESETS.find((x) => x.id === id);
        return p ? `${p.label} (${p.hint})` : id;
      });
      const resp = await fetch(API_BASE + "/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          lat: coords.lat,
          lng: coords.lng,
          craving: craving.trim() + tempHint,
          presets: presetDescriptions,
          local_iso: localIso(now),
          weekday: (now.getDay() + 6) % 7,
          dietary: dietary,
          open_only: openOnly,
        }),
      });
      if (!resp.ok) throw new Error("Server " + resp.status);
      const data = await resp.json();
      setResult(data);
      setTimeout(() => {
        if (resultsRef.current) {
          resultsRef.current.scrollIntoView({ behavior: "smooth" });
        }
      }, 100);
    } catch (e) {
      setError("Couldn't reach the recommender. Is the backend running on " + API_BASE + "?");
    } finally {
      setLoading(false);
    }
  }

  function onKeyDown(e) {
    if (e.key === "Enter") getRecs();
  }

  return (
    <div className="page">
      <header className="header">
        <div className="eyebrow">cravings to real tables, open now</div>
        <h1 className="title">
          What are you <span className="title-accent">feeling</span>?
        </h1>
        <p className="sub">
          Describe the mood. We turn it into cuisines and find places near you
          that are actually open.
        </p>
        <div className="loc-row">
          <span className={"loc-dot " + (coords ? "loc-on" : "loc-off")} />
          {coords
            ? "Located, using spots near you"
            : geoError || "Finding your location..."}
        </div>
      </header>

      <section className="card">
        <div className="section-label">Pick a mood</div>
        <div className="preset-grid">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              onClick={() => togglePreset(p.id)}
              className={"preset" + (selected.includes(p.id) ? " preset-on" : "")}
            >
              <span className="preset-label">{p.label}</span>
              <span className="preset-hint">{p.hint}</span>
            </button>
          ))}
        </div>

        <div className="section-label">or say it your way</div>
        <input
          className="craving-input"
          value={craving}
          onChange={(e) => setCraving(e.target.value)}
          onKeyDown={onKeyDown}
          placeholder="something warm for a rainy night, crispy and a little spicy..."
        />

        <div className="section-label">Temperature preference</div>
        <div className="temp-row">
          {TEMP_PREFS.map((t) => (
            <button
              key={t.id}
              onClick={() => setTempPref(t.id)}
              className={"temp-btn" + (tempPref === t.id ? " temp-btn-on" : "")}
            >
              <span className="temp-label">{t.label}</span>
              <span className="temp-hint">{t.hint}</span>
            </button>
          ))}
        </div>

        <div className="row-between">
          <div className="chip-row">
            {DIETARY.map((d) => (
              <button
                key={d}
                onClick={() => toggleDiet(d)}
                className={"chip" + (dietary.includes(d) ? " chip-on" : "")}
              >
                {d}
              </button>
            ))}
          </div>
          <label className="toggle">
            <input
              type="checkbox"
              checked={openOnly}
              onChange={(e) => setOpenOnly(e.target.checked)}
            />
            Open now only
          </label>
        </div>

        <button
          className="cta"
          onClick={getRecs}
          disabled={!canSubmit || loading}
        >
          {loading ? "Reading the room..." : "Find my table"}
        </button>
        {error && <div className="error">{error}</div>}
      </section>

      {result && (
        <section className="results" ref={resultsRef}>
          <div className="plan-bar">
            <div className="plan-cuisines">
              {result.plan.cuisines.map((c) => (
                <span key={c} className="plan-chip">{c}</span>
              ))}
            </div>
            <p className="plan-rationale">{result.plan.rationale}</p>
          </div>

          {result.restaurants.length === 0 && (
            <div className="empty">
              Nothing open matched that craving nearby. Try turning off "open now"
              or a different mood.
            </div>
          )}

          <div className="card-grid">
            {result.restaurants.map((r, i) => (
              <article key={r.place_id} className="r-card">
                <div className="r-rank">{String(i + 1).padStart(2, "0")}</div>
                <div className="r-top">
                  <h3 className="r-name">{r.name}</h3>
                  <span className="r-cuisine">{r.cuisine}</span>
                </div>
                <div className="r-meta">
                  {r.rating != null && (
                    <span className="r-rating">
                      &#9733; {r.rating.toFixed(1)}
                      <span className="r-count">
                        {" "}({r.review_count ? r.review_count.toLocaleString() : 0})
                      </span>
                    </span>
                  )}
                  {r.price_level != null && (
                    <span className="r-price">{PRICE[r.price_level]}</span>
                  )}
                  {r.drive_min != null ? (
                    <span className="r-travel">
                      <span className="r-travel-mode">🚗 {r.drive_min} min</span>
                      {r.walk_min != null && (
                        <span className="r-travel-mode">🚶 {r.walk_min} min</span>
                      )}
                    </span>
                  ) : r.distance_mi != null && (
                    <span className="r-dist">{r.distance_mi.toFixed(1)} mi</span>
                  )}
                  {r.open_now === true && (
                    <span className={r.closes_soon ? "open-soon" : "open-now"}>
                      {r.closes_soon ? "closes soon" : "open now"}
                    </span>
                  )}
                  {r.open_now === false && <span className="closed">closed</span>}
                </div>
                {r.vibe && <p className="r-vibe">{r.vibe}</p>}
                {r.signature_dishes && r.signature_dishes.length > 0 && (
                  <div className="dish-row">
                    {r.signature_dishes.map((d) => (
                      <span key={d} className="dish">{d}</span>
                    ))}
                  </div>
                )}
                {r.hours_today && <div className="hours">{r.hours_today}</div>}
                {r.maps_uri && (
                  <a className="map-link" href={r.maps_uri} target="_blank" rel="noreferrer">
                    Open in Maps
                  </a>
                )}
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export default App;
