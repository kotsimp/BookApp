// Light theme by day, dark at night. The automatic theme follows sunrise and sunset for the date (Athens when the
// browser is on Greek time). The theme button switches by hand, and that choice holds until the next sunrise or
// sunset; then the automatic theme takes over again. Loaded in <head> so the page never flashes the other theme.
const BookAppTheme = (() => {
  const CHOICE_KEY = 'bookapp_theme_choice';  // {"theme": "light" | "dark", "until": ms}
  const OLD_KEY = 'bookapp_theme';             // the former lasting choice: replaced by the automatic theme
  const RAD = Math.PI / 180;
  const DAY_MS = 86400000;

  function guessPlace() {
    let zone = '';
    try { zone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (_) {}
    if (zone === 'Europe/Athens') return [37.98, 23.73];
    if (zone === 'Asia/Nicosia' || zone === 'Asia/Famagusta' || zone === 'Europe/Nicosia') return [35.17, 33.36];
    // elsewhere: the longitude from the standard time offset; daylight saving in January means the south
    const year = new Date().getFullYear();
    const jan = new Date(year, 0, 1).getTimezoneOffset();
    const jul = new Date(year, 6, 1).getTimezoneOffset();
    return [jan < jul ? -35 : 45, -Math.max(jan, jul) / 4];
  }

  let place = guessPlace();

  // Sunrise and sunset (ms) of the day around `instant`, from the standard solar equations (sun 0.833° below the
  // horizon). {always: 'day' | 'night'} where the sun does not rise or set that day.
  function sunTimes(instant, lat, lon) {
    const julian = instant / DAY_MS + 2440587.5 - 2451545;
    const lw = -lon * RAD;
    const cycle = Math.round(julian - 0.0009 - lw / (2 * Math.PI));
    const approx = 0.0009 + lw / (2 * Math.PI) + cycle;
    const m = RAD * (357.5291 + 0.98560028 * approx);
    const c = RAD * (1.9148 * Math.sin(m) + 0.02 * Math.sin(2 * m) + 0.0003 * Math.sin(3 * m));
    const l = m + c + RAD * 102.9372 + Math.PI;
    const noon = 2451545 + approx + 0.0053 * Math.sin(m) - 0.0069 * Math.sin(2 * l);
    const dec = Math.asin(Math.sin(RAD * 23.4397) * Math.sin(l));
    const cosH = (Math.sin(RAD * -0.833) - Math.sin(lat * RAD) * Math.sin(dec)) / (Math.cos(lat * RAD) * Math.cos(dec));
    if (cosH > 1) return { always: 'night' };
    if (cosH < -1) return { always: 'day' };
    const half = Math.acos(cosH) / (2 * Math.PI);
    const toMs = (j) => (j - 2440587.5) * DAY_MS;
    return { rise: toMs(noon - half), set: toMs(noon + half) };
  }

  // The local day's sun times: computed at local noon, so the right day is taken in any time zone
  function sunOfDay(now) {
    const d = new Date(now);
    return sunTimes(new Date(d.getFullYear(), d.getMonth(), d.getDate(), 12).getTime(), place[0], place[1]);
  }

  function autoTheme(now = Date.now()) {
    const sun = sunOfDay(now);
    if (sun.always) return sun.always === 'day' ? 'light' : 'dark';
    return now >= sun.rise && now < sun.set ? 'light' : 'dark';
  }

  // When the automatic theme changes next (the next sunrise or sunset); a day later where the sun stays up or down
  function nextChange(now = Date.now()) {
    const sun = sunOfDay(now);
    if (!sun.always) {
      if (now < sun.rise) return sun.rise;
      if (now < sun.set) return sun.set;
    }
    const tomorrow = sunOfDay(now + DAY_MS);
    return tomorrow.always ? now + DAY_MS : tomorrow.rise;
  }

  function readChoice(now) {
    try {
      const c = JSON.parse(localStorage.getItem(CHOICE_KEY) || 'null');
      if (c && (c.theme === 'light' || c.theme === 'dark') && Number(c.until) > now) return c;
    } catch (_) {}
    return null;
  }

  function current(now = Date.now()) {
    const choice = readChoice(now);
    return choice ? choice.theme : autoTheme(now);
  }

  const listeners = [];

  function apply(now = Date.now()) {
    const theme = current(now);
    if (document.documentElement.getAttribute('data-theme') !== theme) {
      document.documentElement.setAttribute('data-theme', theme);
    }
    listeners.forEach((fn) => { try { fn(theme); } catch (_) {} });
    return theme;
  }

  // The button: the other theme, until the next sunrise or sunset. Choosing the automatic one clears the choice.
  function toggle(now = Date.now()) {
    const next = current(now) === 'dark' ? 'light' : 'dark';
    try {
      if (next === autoTheme(now)) localStorage.removeItem(CHOICE_KEY);
      else localStorage.setItem(CHOICE_KEY, JSON.stringify({ theme: next, until: nextChange(now) }));
    } catch (_) {}
    return apply(now);
  }

  function isManual(now = Date.now()) {
    return readChoice(now) !== null;
  }

  function onChange(fn) {
    listeners.push(fn);
  }

  try { localStorage.removeItem(OLD_KEY); } catch (_) {}
  apply();
  // sunrise and sunset come while the page stays open (and after a computer wakes up)
  setInterval(() => apply(), 60000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) apply(); });

  return {
    current, toggle, apply, onChange, isManual, nextChange, autoTheme,
    _sunTimes: sunTimes, _setPlace: (lat, lon) => { place = [lat, lon]; },
  };
})();
