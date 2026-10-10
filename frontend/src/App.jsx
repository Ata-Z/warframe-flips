import { useCallback, useEffect, useMemo, useState } from "react";
import { supabase } from "./supabase";
import "./App.css";

const show = (v) => (v === null || v === undefined ? "—" : v);

export default function App() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [minProfit, setMinProfit] = useState("");
  const [sortKey, setSortKey] = useState("profit");
  const [sortDir, setSortDir] = useState("desc");

  const load = useCallback(async () => {
    const { data, error } = await supabase.from("mod_prices").select("*");
    if (error) setError(error.message);
    else { setRows(data); setError(null); }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, 60_000); // refresh every minute
    return () => clearInterval(id);
  }, [load]);

  const visible = useMemo(() => {
    if (!rows) return [];
    const q = search.toLowerCase().replaceAll(" ", "_");
    return rows
      .filter((r) => r.mod.includes(q))
      .filter(
        (r) =>
          minProfit === "" ||
          (r.profit !== null && r.profit >= Number(minProfit))
      )
      .sort((a, b) => {
        const av = a[sortKey], bv = b[sortKey];
        if (av == null && bv == null) return 0;
        if (av == null) return 1;   // nulls always last
        if (bv == null) return -1;
        const diff = typeof av === "string" ? av.localeCompare(bv) : av - bv;
        return sortDir === "asc" ? diff : -diff;
      });
  }, [rows, search, minProfit, sortKey, sortDir]);

  function toggleSort(key) {
    if (key === sortKey) setSortDir(sortDir === "asc" ? "desc" : "asc");
    else { setSortKey(key); setSortDir("desc"); }
  }

  if (error) return <main><p>Could not load data: {error}</p></main>;
  if (!rows) return <main><p>Loading…</p></main>;

  const updated = rows.reduce((m, r) => (r.updated_at > m ? r.updated_at : m), "");

  const th = (key, label) => (
    <th onClick={() => toggleSort(key)}>
      {label} {sortKey === key ? (sortDir === "asc" ? "▲" : "▼") : ""}
    </th>
  );

  return (
    <main>
      <h1>Warframe Mod Flips</h1>
      <p className="muted">
        Last updated: {updated ? new Date(updated).toLocaleString() : "never"}
      </p>

      <div className="controls">
        <input
          placeholder="Search mods…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <label>
          Min profit:{" "}
          <input
            type="number"
            value={minProfit}
            onChange={(e) => setMinProfit(e.target.value)}
          />
        </label>
      </div>

      <table>
        <thead>
          <tr>
            {th("mod", "Mod")}
            {th("seller_price", "Buy at (p)")}
            {th("buyer_price", "Sell at (p)")}
            {th("profit", "Profit (p)")}
            {th("seller_count", "Sellers")}
            {th("buyer_count", "Buyers")}
          </tr>
        </thead>
        <tbody>
          {visible.map((r) => (
            <tr key={r.mod}>
              <td>
                <a
                  href={`https://warframe.market/items/${r.mod}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  {r.mod.replaceAll("_", " ")}
                </a>
              </td>
              <td>{show(r.seller_price)}</td>
              <td>{show(r.buyer_price)}</td>
              <td className={r.profit > 0 ? "good" : r.profit < 0 ? "bad" : ""}>
                {show(r.profit)}
              </td>
              <td>{r.seller_count}</td>
              <td>{r.buyer_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}