/* theme.js - light / dark appearance. Load as the FIRST script in <head> on every page (before auth.js and the stylesheets),
   so the theme is set before the first paint (no flash).
   Contract (other scripts rely on it):
   - document.documentElement.dataset.theme is always 'dark' or 'light'; default 'dark'; the choice is kept in localStorage 'tv_theme'
   - window.TVTheme = { get(), set(t), toggle(), css(name) }; css('--text') = computed value of that CSS variable on <html>
   - every change dispatches window 'tvthemechange' with detail { theme }. Chart.js globals (text, grid, tooltip) follow the tokens and
     every existing chart is updated; renderers with colours of their own (heat map, growth curve, analytics charts) listen and redraw
   - one sun / moon button (.theme-btn) goes into the page header: before #user-menu if there is one, else at the end of the header
   Colours live in the stylesheets (:root = dark, :root[data-theme="light"] = light); the table below is only a fallback for css(). */
'use strict';
(function () {
  if (window.TVTheme) return;
  const KEY = 'tv_theme', root = document.documentElement;
  const FALLBACK = {
    dark: { '--bg': '#131722', '--surface': '#1E2130', '--surface2': '#1A1D2E', '--border': '#2A2E39', '--text': '#D1D4DC', '--text-dim': '#787B86',
      '--accent': '#2962FF', '--green': '#26A69A', '--red': '#EF5350', '--gold': '#F7C948', '--white': '#FFFFFF', '--tip-bg': '#0D1017' },
    light: { '--bg': '#FFFFFF', '--surface': '#F7F8FA', '--surface2': '#EEF0F4', '--border': '#DCE0E8', '--text': '#131722', '--text-dim': '#5F6370',
      '--accent': '#2962FF', '--green': '#067A66', '--red': '#C9303C', '--gold': '#8A6600', '--white': '#0B0E14', '--tip-bg': '#FFFFFF' },
  };
  const valid = t => t === 'dark' || t === 'light';
  function stored() { try { const v = localStorage.getItem(KEY); return valid(v) ? v : null; } catch (e) { return null; } }
  function save(t) { try { localStorage.setItem(KEY, t); } catch (e) { /* private mode: the choice lasts for this page only */ } }

  let theme = stored() || 'dark';
  root.dataset.theme = theme;

  function css(name) {
    let v = '';
    try { v = getComputedStyle(root).getPropertyValue(name).trim(); } catch (e) { /* no style yet */ }
    return v || FALLBACK[theme][name] || '';
  }

  // Chart.js globals: axis text, grid lines, tooltip. Charts that set their own colours redraw on 'tvthemechange'.
  function chartDefaults() {
    const Ch = window.Chart;
    if (!Ch || !Ch.defaults) return false;
    const D = Ch.defaults, T = D.plugins && D.plugins.tooltip;
    D.color = css('--text-dim');
    D.borderColor = css('--border');
    if (T) {
      T.backgroundColor = css('--tip-bg');
      T.titleColor = css('--white');
      T.bodyColor = css('--text');
      T.footerColor = css('--text');
      T.borderColor = css('--border');
      T.borderWidth = 1;
    }
    return true;
  }
  function repaintCharts() {
    if (!chartDefaults()) return;
    Object.values(window.Chart.instances || {}).forEach(c => { try { c.update('none'); } catch (e) { /* chart being destroyed */ } });
  }

  // ───────── toggle button ─────────
  const SUN = '<svg class="tb-sun" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>';
  const MOON = '<svg class="tb-moon" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>';
  let btn = null;
  function label() {
    if (!btn) return;
    const t = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    btn.setAttribute('aria-label', t);
    btn.title = t;
  }
  function inject() {
    if (btn || document.querySelector('.theme-btn')) return;
    btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'theme-btn';
    btn.innerHTML = SUN + MOON;            // CSS shows the sun in dark mode (switch to light) and the moon in light mode
    label();
    btn.addEventListener('click', () => api.toggle());
    const um = document.getElementById('user-menu');
    if (um && um.parentNode) { um.parentNode.insertBefore(btn, um); return; }
    const head = document.querySelector('#main-header .header-right, #top, header.auth-top, header');
    if (head) { head.appendChild(btn); return; }
    const logo = document.querySelector('.auth-card .logo');      // sign-in page: no header, the button sits at the right of the logo row
    if (logo) { logo.appendChild(btn); return; }
    btn.classList.add('floating');
    document.body.appendChild(btn);
  }

  function apply(t, persist) {
    if (!valid(t)) return;
    if (persist) save(t);
    if (t === theme && root.dataset.theme === t) return;
    theme = t;
    root.dataset.theme = t;
    label();
    repaintCharts();
    window.dispatchEvent(new CustomEvent('tvthemechange', { detail: { theme: t } }));
  }

  const api = window.TVTheme = {
    get: () => theme,
    set: t => apply(t, true),
    toggle: () => apply(theme === 'dark' ? 'light' : 'dark', true),
    css,
    chartDefaults,                          // helper for responsive.js (sets the Chart.js colour defaults right after Chart.js loads)
  };

  // another tab changed the theme
  window.addEventListener('storage', e => { if (e.key === KEY) apply(valid(e.newValue) ? e.newValue : 'dark', false); });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => { inject(); chartDefaults(); });
  else { inject(); chartDefaults(); }
})();
