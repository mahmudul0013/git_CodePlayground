/* pulse.js - one light scheduler for every refresh on a page (load after theme.js / auth.js, before the page scripts).
   - One 15 s timer per page instead of one per job.
   - Nothing runs while the tab is hidden; when it becomes visible again every job that is due runs once.
   - Market-aware: each job has an interval for market hours and a (much longer) one for closed hours.
     Market hours = Mon-Fri 08:00-22:30 Stockholm time (covers Nordic, German and US sessions of the holdings).
   - A job never runs twice at the same time.
     TVPulse.every(name, fn, { open: ms, closed: ms, now: false })   register (now: true = run at once)
     TVPulse.run(name)                                                 run a job now (e.g. after an upload)
     TVPulse.marketOpen()                                              true during market hours
   Testing: localStorage tv_market = 'open' | 'closed' forces the market state. */
'use strict';
(function () {
  if (window.TVPulse) return;
  const jobs = new Map();
  const TICK = 15000;
  const forced = () => { try { return localStorage.getItem('tv_market'); } catch (e) { return null; } };

  function marketOpen() {
    const f = forced();
    if (f === 'open') return true;
    if (f === 'closed') return false;
    try {
      const parts = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Stockholm', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(new Date());
      const get = t => (parts.find(p => p.type === t) || {}).value;
      const day = get('weekday'), mins = +get('hour') * 60 + +get('minute');
      return !['Sat', 'Sun'].includes(day) && mins >= 8 * 60 && mins <= 22 * 60 + 30;
    } catch (e) {
      const d = new Date(), w = d.getDay(), h = d.getHours();
      return w > 0 && w < 6 && h >= 8 && h < 23;
    }
  }

  async function runJob(j) {
    if (j.busy) return;
    j.busy = true;
    j.last = Date.now();
    try { await j.fn(); } catch (e) { /* each job handles its own errors; keep the schedule */ }
    j.busy = false;
  }

  function tick() {
    if (document.visibilityState === 'hidden') return;
    const open = marketOpen(), now = Date.now();
    jobs.forEach(j => { if (now - j.last >= (open ? j.open : j.closed)) runJob(j); });
  }

  function every(name, fn, opt) {
    const o = opt || {};
    const j = { fn, open: o.open || 60000, closed: o.closed || o.open || 60000, last: o.now ? 0 : Date.now(), busy: false };
    jobs.set(name, j);
    if (o.now) runJob(j);
  }

  function run(name) { const j = jobs.get(name); if (j) return runJob(j); }

  setInterval(tick, TICK);
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') tick(); });
  window.TVPulse = { every, run, marketOpen };
})();
