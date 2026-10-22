// Beat clock, 31 acted emotions, dances and shot timing.
//
// Adapted from John Heibel, ClaudeAnimationBase (MIT), Copyright (c) 2026 John Heibel.
// https://github.com/JohnHeibel/ClaudeAnimationBase
// Ported: timing helpers, emotion pose functions, move vocabulary, shot lookup.
// Not included: the Clawd drawing, p5.js / p5.brush, model-sheet images and the demo scene.
// templates/character-beat.html draws an original geometric figure from these poses.
// Two-item emotion keys are accepted (the upstream guide writes them that way).
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  root.StoryPerformance = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  const TAU = Math.PI * 2;
  const clock = { bpm: 120, offset: 0, duration: 8 };
  const PAL = {
    paper: "#F3EBDC", ink: "#2B2233", clay: "#D97757", clayDk: "#A84D33", clayLt: "#F2A283",
  };
  const TINT = { pale: "#F6E6D2", flush: "#E23E36", blue: "#6D86BE", rosy: "#EF8EA8", green: "#98B25E", gold: "#F0BE46" };

  const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
  const lerp = (a, b, x) => a + (b - a) * x;
  const ease = x => { x = clamp(x); return x * x * (3 - 2 * x); };
  const easeOut = x => 1 - Math.pow(1 - clamp(x), 3);
  const easeIn = x => Math.pow(clamp(x), 3);
  const backOut = x => { x = clamp(x); const s = 1.9; return 1 + (s + 1) * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2); };
  const seg = (t, a, b) => clamp((t - a) / (b - a));
  const frac = x => x - Math.floor(x);
  const beatLen = () => 60 / clock.bpm;
  const bpOf = t => (t - clock.offset) / beatLen();
  const beatN = t => Math.floor(bpOf(t));
  const pulse = (t, k = 6) => Math.exp(-frac(bpOf(t)) * k);
  const pulse2 = (t, k = 6) => Math.exp(-frac(bpOf(t) * 2) * k);
  const onTwos = t => Math.floor(t * 12 + 1e-6) / 12;
  const spring = (t, t0, k = 6, w = 18) => t < t0 ? 0 : Math.exp(-k * (t - t0)) * Math.sin(w * (t - t0));

  function mixCol(a, b, k) {
    const pa = parseInt(a.slice(1), 16), pb = parseInt(b.slice(1), 16);
    const c = i => Math.round(lerp((pa >> i) & 255, (pb >> i) & 255, clamp(k)));
    return "#" + ((1 << 24) + (c(16) << 16) + (c(8) << 8) + c(0)).toString(16).slice(1);
  }
  function tintCols(o) {
    const c = { col: o.col || PAL.clay, dk: o.dk || PAL.clayDk, lt: o.lt || "#F5B394" };
    const tc = o.tint && (TINT[o.tint] || o.tint), k = clamp(o.tintK ?? 1);
    if (!tc || k <= 0) return c;
    return {
      col: mixCol(c.col, tc, .55 * k),
      dk: mixCol(c.dk, mixCol(tc, PAL.ink, .35), .5 * k),
      lt: mixCol(c.lt, mixCol(tc, "#FFFFFF", .4), .45 * k),
    };
  }
  function spinView(a) {
    const K = [["front", 0], ["q", 0], ["side", 0], ["qback", 0], ["back", 0], ["qback", 1], ["side", 1], ["q", 1]];
    const pair = K[((Math.round(a * 8) % 8) + 8) % 8];
    return { view: pair[0], flip: !!pair[1] };
  }
  function turn(t, t0, t1, a0, a1) {
    const k = ease(seg(t, t0, t1)), v = spinView(lerp(a0, a1, k));
    return Object.assign({}, v, { smear: t > t0 && t < t1 ? .55 * Math.sin(k * Math.PI) : 0, smearDir: 0 });
  }
  function kf(t, keys, e = ease) {
    if (t <= keys[0][0]) return keys[0][1];
    for (let i = 1; i < keys.length; i++) {
      if (t < keys[i][0]) {
        const a = keys[i - 1], b = keys[i], k = e((t - a[0]) / (b[0] - a[0]));
        return Array.isArray(a[1]) ? a[1].map((v, j) => lerp(v, b[1][j], k)) : lerp(a[1], b[1], k);
      }
    }
    return keys[keys.length - 1][1];
  }
  function jump(t, t0, t1, h = 3) {
    if (t < t0 - .12) return { dy: 0, sq: 0 };
    if (t < t0) return { dy: 0, sq: .18 * ease(seg(t, t0 - .12, t0)) };
    if (t < t1) {
      const k = (t - t0) / (t1 - t0);
      return { dy: -h * 4 * k * (1 - k), sq: -.16 * Math.abs(1 - 2 * k) };
    }
    const a = t - t1;
    return { dy: 0, sq: .22 * Math.exp(-8 * a) * Math.cos(20 * a) };
  }
  function take(t, t0, amt = 1) {
    if (t < t0 - .1) return { sq: 0, dy: 0 };
    if (t < t0) return { sq: .12 * amt * ease(seg(t, t0 - .1, t0)), dy: 0 };
    const a = t - t0;
    return {
      sq: -.26 * amt * Math.exp(-6 * a) * Math.cos(16 * a),
      dy: -1.2 * amt * Math.exp(-7 * a) * Math.max(0, Math.cos(9 * a)),
    };
  }

  const _b = t => {
    const bp = bpOf(t), s1 = Math.sin(bp * Math.PI);
    return { bp, s1, ab: Math.abs(s1), hit: pulse(t), s2: Math.sin(bp * TAU), f: frac(bp) };
  };

  // Each emotion is a face and a way of moving. body(t) returns pose offsets. take is the
  // reaction size when the performance switches into this emotion. fade marks a one-off emote.
  const EMO = {
    neutral:    { eyes: "normal", take: .3, body: t => { const b = _b(t); return { dy: -.25 * b.ab, sq: .03 * b.hit, aL: .15 + .05 * b.s1, aR: .15 - .05 * b.s1 }; } },
    happy:      { eyes: "happy", mouth: "smile", blush: .3, take: .6, body: t => { const b = _b(t); return { dy: -1.2 * b.ab, sq: .1 * b.hit, aL: .4 + .4 * b.s1, aR: .4 - .4 * b.s1 }; } },
    excited:    { eyes: "wide", mouth: "open", emote: "spark", take: 1, body: t => { const b = _b(t), h = Math.abs(b.s2); return { dy: -2.4 * h, sq: .16 * pulse2(t) - .06 * h, aL: 1 + .5 * Math.sin(b.bp * TAU * 2), aR: 1 - .5 * Math.sin(b.bp * TAU * 2) }; } },
    laugh:      { eyes: "squeeze", mouth: "laugh", blush: .45, take: .8, body: t => { const c = Math.abs(Math.sin(t * TAU * 5)); return { dy: -.45 * c, sq: .08 * c - .04, rot: -.07 + .03 * Math.sin(t * TAU * 5), aL: -.35 + .12 * c, aR: -.35 + .12 * c }; } },
    love:       { eyes: "heart", mouth: "cat", blush: .8, tint: "rosy", tintK: .5, emote: "hearts", take: .7, body: t => { const b = _b(t), s = Math.sin(b.bp * Math.PI / 2); return { rot: .08 * s, dx: .5 * s, dy: -.6 * b.ab, sq: .05 * b.hit, aL: -.1 + .15 * b.s1, aR: -.1 - .15 * b.s1 }; } },
    shy:        { eyes: "look", mouth: "wobble", blush: 1, take: .3, body: t => { const b = _b(t), s = Math.sin(b.bp * Math.PI / 2); return { lookX: -.7, lookY: .8, sq: .06, rot: -.05 + .02 * s, dx: .15 * s, aL: -.55 + .15 * Math.sin(t * TAU * 1.5), aR: -.6 - .12 * Math.sin(t * TAU * 1.5) }; } },
    proud:      { eyes: "closed", mouth: "smile", tint: "gold", tintK: .3, emote: "spark", take: .5, body: t => { const b = _b(t); return { sq: -.1 - .03 * b.ab, dy: -.3 * b.hit, aL: -.9, aR: -.9, rot: .02 * b.s1 }; } },
    smug:       { eyes: "narrow", mouth: "smirk", take: .4, body: t => { const b = _b(t), s = Math.sin(b.bp * Math.PI / 2); return { lookX: .4, rot: -.06 + .03 * s, dy: -.2 * b.ab, aL: -.5, aR: .5 + .15 * s }; } },
    relieved:   { eyes: "closed", mouth: "smile", emote: "sweat", take: .4, body: t => { const b = _b(t), br = Math.sin(t * TAU * .35); return { sq: .05 + .05 * br, dy: -.15 * b.ab, aL: -.7 + .1 * br, aR: -.7 + .1 * br }; } },
    sad:        { eyes: "sad", mouth: "frown", tint: "blue", tintK: .35, gloom: .35, emote: "cloud", take: .3, body: t => { const b = _b(t), s = Math.sin(b.bp * Math.PI / 4); return { sq: .08 + .02 * s, rot: .03 * s, aL: -.75, aR: -.75, lookY: .5 }; } },
    cry:        { eyes: "cry", mouth: "wail", tint: "blue", tintK: .2, take: .8, body: t => { const b = _b(t), sob = Math.sin(b.f * Math.PI) * Math.exp(-b.f * 2); return { sq: .14 * sob - .02, dy: -.7 * sob, aL: .9 + .15 * Math.sin(t * TAU * 6), aR: .9 - .15 * Math.sin(t * TAU * 6), rot: .03 * b.s1 }; } },
    angry:      { eyes: "angry", mouth: "teeth", tint: "flush", tintK: .45, emote: "anger", take: .8, body: t => { const b = _b(t); return { dx: .1 * Math.sin(t * TAU * 18), sq: .12 * b.hit, aL: -.3 + .1 * b.hit, aR: -.3 + .1 * b.hit }; } },
    furious:    { eyes: "red", lid: .28, tint: "flush", tintK: .85, emote: "steam", take: 1.2, body: t => { const b = _b(t); return { dx: .22 * Math.sin(t * TAU * 20), rot: .025 * Math.sin(t * TAU * 13), sq: .2 * b.hit, dy: -.8 * Math.sin(b.f * Math.PI) * (1 - b.f), aL: 1 + .2 * Math.sin(t * TAU * 9), aR: 1 - .2 * Math.sin(t * TAU * 9) }; } },
    scared:     { eyes: "scared", mouth: "wobble", tint: "pale", tintK: .6, emote: "sweat", take: 1.1, body: t => ({ dx: .1 * Math.sin(t * TAU * 22), sq: -.06, aL: 1 + .08 * Math.sin(t * TAU * 17), aR: 1 + .08 * Math.sin(t * TAU * 19), lookX: .6 * Math.sign(Math.sin(t * 2.3)) }) },
    surprised:  { eyes: "wide", mouth: "O", emote: "!", fade: true, take: 1.3, body: t => { const b = _b(t); return { sq: -.12, dy: -.3 - .15 * b.ab, aL: 1.1 + .05 * b.s2, aR: 1.1 - .05 * b.s2 }; } },
    confused:   { eyes: ["narrow", "wide"], mouth: "wobble", emote: "?", take: .6, body: t => { const b = _b(t); return { rot: .1 * Math.sin(b.bp * Math.PI / 4), aL: .1, aR: 1.5 + .15 * Math.sin(t * TAU * 3), dy: -.15 * b.ab }; } },
    thinking:   { eyes: "look", mouth: "flat", emote: "dots", take: .4, body: t => { const b = _b(t); return { lookX: .5, lookY: -.8, rot: .05, aR: .9, aL: -.3 + .25 * Math.sin(b.f * Math.PI), dy: -.1 * b.ab }; } },
    idea:       { eyes: "shine", mouth: "grin", emote: "bulb", take: 1.1, body: t => { const b = _b(t); return { dy: -1 * b.ab, sq: -.05 + .1 * b.hit, aR: 1.55 + .1 * b.s2, aL: .2 + .2 * b.s1 }; } },
    determined: { eyes: "determined", mouth: "flat", take: .7, body: t => { const b = _b(t), p1 = Math.sin(b.f * Math.PI), p2 = Math.abs(Math.cos(b.f * Math.PI)); return { rot: .06, sq: -.04 + .06 * b.hit, dy: -.3 * b.ab, aL: .1 + .7 * p1, aR: .1 + .7 * p2 }; } },
    sleepy:     { eyes: "sleepy", mouth: "o", emote: "zzz", take: .2, body: t => { const br = Math.sin(t * TAU * .3); return { sq: .05 + .05 * br, rot: .06 * Math.sin(t * .8), aL: -.6, aR: -.6 }; } },
    bored:      { eyes: "narrow", mouth: "flat", take: .2, body: t => { const f = frac(bpOf(t) / 4), sigh = f < .3 ? ease(f / .3) : 1 - ease((f - .3) / .7); return { lookX: -.3, lookY: .4, sq: .08 - .14 * sigh, rot: -.04, aL: -.85 + .05 * Math.sin(t * 2), aR: -.85 - .05 * Math.sin(t * 2) }; } },
    nervous:    { eyes: "look", mouth: "wobble", tint: "pale", tintK: .2, emote: "sweat", take: .5, body: t => { const b = _b(t); return { lookX: beatN(t) % 2 ? .8 : -.8, dx: .3 * b.s1, sq: .04, aL: -.1 + .2 * Math.sin(t * TAU * 5), aR: -.1 + .2 * Math.sin(t * TAU * 5 + 1) }; } },
    suspicious: { eyes: "narrow", mouth: "flat", take: .4, body: t => { const s = Math.sin(t * TAU * .25); return { lookX: s, rot: -.08 * s, dx: .4 * s, sq: .04, aL: -.4, aR: -.4 }; } },
    disgusted:  { eyes: "squeeze", mouth: "wobble", tint: "green", tintK: .5, take: .8, body: t => { const a = frac(bpOf(t) / 2) * beatLen() * 2, sh = Math.exp(-a * 6) * Math.sin(a * 45); return { rot: -.1, dx: -.3 + .15 * sh, sq: .05, aL: .7 + .2 * sh, aR: .7 - .2 * sh }; } },
    dizzy:      { eyes: "swirl", mouth: "wobble", emote: "stars", take: .7, body: t => { const a = t * TAU * .8; return { rot: .12 * Math.sin(a), dx: .7 * Math.sin(a), dy: -.3 * Math.abs(Math.cos(a)), aL: .3 + .6 * Math.sin(a * 1.3), aR: .3 - .6 * Math.sin(a * 1.3) }; } },
    cool:       { eyes: "shades", mouth: "smirk", emote: "music", take: .4, body: t => { const b = _b(t); return { rot: .04 * b.hit, dy: -.35 * b.hit, sq: .06 * b.hit, aL: -.4, aR: .7 + .1 * b.s1 }; } },
    starstruck: { eyes: "spark", mouth: "open", tint: "gold", tintK: .3, take: 1, body: t => { const b = _b(t), h = Math.abs(b.s2); return { dy: -1.6 * h, sq: .1 * pulse2(t), aL: 1.1 + .35 * Math.sin(b.bp * TAU * 2), aR: 1.1 + .35 * Math.sin(b.bp * TAU * 2) }; } },
    ko:         { eyes: "x", mouth: "wobble", tint: "pale", tintK: .3, emote: "stars", take: 1, body: t => ({ sq: .28 + .02 * Math.sin(t * 3), rot: .12, aL: -1, aR: -.9 }) },
    playful:    { eyes: "wink", mouth: "tongue", take: .6, body: t => { const b = _b(t), side = beatN(t) % 2 ? 1 : -1, k = lerp(-side, side, easeOut(clamp(b.f * 3))); return { dx: .8 * k, dy: -1.4 * b.ab, rot: .1 * k, sq: .1 * b.hit, aL: .65 + .55 * k, aR: .65 - .55 * k }; } },
    mischief:   { eyes: "narrow", mouth: "grin", gloom: .3, take: .5, body: t => { const r = Math.sin(t * TAU * 4); return { lookX: .3, sq: .07, rot: .04, aL: -.05 + .15 * r, aR: -.05 - .15 * r, dy: -.1 * Math.abs(r) }; } },
    hopeful:    { eyes: "shine", mouth: "cat", blush: .35, take: .5, body: t => { const b = _b(t); return { sq: -.06 - .02 * b.ab, dy: -.25 * b.ab, lookY: -.4, aL: .5 + .05 * b.s1, aR: .5 - .05 * b.s1, rot: .03 * Math.sin(b.bp * Math.PI / 2) }; } },
  };

  function feel(name, t, over) {
    over = over || {};
    const known = Object.prototype.hasOwnProperty.call(EMO, name);
    const E = known ? EMO[name] : EMO.neutral;
    return {
      emotion: known ? name : "neutral",
      eyes: E.eyes, mouth: E.mouth, tint: E.tint, tintK: E.tintK ?? 1,
      blush: E.blush || 0, gloom: E.gloom || 0, lid: E.lid || 0, emote: E.emote,
      ...(E.body ? E.body(t) : {}),
      ...over,
    };
  }

  function emotions(t, keys, o = {}) {
    if (!keys || !keys.length) throw new Error("emotion keys are empty");
    let i = 0;
    while (i + 1 < keys.length && t >= keys[i + 1][0]) i++;
    const tc = keys[i][0], name = keys[i][1], over = keys[i][2] || {};
    const age = t - tc, cur = feel(name, t, over);
    const tn = i + 1 < keys.length ? keys[i + 1][0] : Infinity;
    const scale = o.take ?? 1;
    const E = EMO[name] || EMO.neutral;
    let squint = cur.squint || 0;
    if (tn - t < .1) squint = Math.max(squint, 1 - (tn - t) / .1);
    if (i > 0 && age < .14) squint = Math.max(squint, 1 - age / .14);
    const prev = i > 0 ? feel(keys[i - 1][1], t, keys[i - 1][2] || {}) : null;
    if (prev && age < .5) {
      const base = { dy: 0, sq: 0, aL: .2, aR: .2, rot: 0, dx: 0, lookX: 0, lookY: 0 };
      const k = backOut(seg(age, 0, .4)), kc = ease(seg(age, 0, .3));
      for (const f in base) cur[f] = lerp(prev[f] ?? base[f], cur[f] ?? base[f], k);
      const a = tintCols(prev), b = tintCols(cur);
      cur.col = mixCol(a.col, b.col, kc);
      cur.dk = mixCol(a.dk, b.dk, kc);
      cur.lt = mixCol(a.lt, b.lt, kc);
      cur.tint = null;
      for (const f of ["blush", "gloom", "lid"]) cur[f] = lerp(prev[f] || 0, cur[f] || 0, kc);
    }
    const landed = prev ? take(t, tc, (E.take ?? .6) * scale) : { sq: 0, dy: 0 };
    const nextName = i + 1 < keys.length ? keys[i + 1][1] : null;
    const En = nextName ? (EMO[nextName] || EMO.neutral) : null;
    const upcoming = En ? take(t, tn, (En.take ?? .6) * scale) : { sq: 0, dy: 0 };
    cur.sq = (cur.sq || 0) + landed.sq + upcoming.sq;
    cur.dy = (cur.dy || 0) + landed.dy + upcoming.dy;
    cur.squint = squint;
    const same = prev && prev.emote === cur.emote;
    cur.emoteK = same ? 1 : seg(age, .06, .32) * (E.fade && !over.emote ? 1 - seg(age, 1.4, 1.8) : 1);
    cur.emoteAge = age;
    return cur;
  }

  const MOVES = ["bounce", "hop", "roof", "sway", "spin", "wave", "walk", "run", "idle", "stomp", "shimmy", "mix"];
  function move(style, t, seed = 0) {
    const bp = bpOf(t), bi = Math.floor(bp), bf = bp - bi, hit = Math.max(0, 1 - bf * 3.5), s1 = Math.sin(bp * Math.PI);
    const ab = Math.abs(s1);
    const o = { dy: 0, sq: 0, aL: .2, aR: .2, rot: 0, walk: null, dx: 0 };
    if (style === "mix") style = ["bounce", "roof", "sway", "spin", "hop", "wave"][(Math.floor(bp / 8) + seed) % 6];
    switch (style) {
      case "bounce": o.dy = -ab * 1.6; o.sq = hit * .12; o.aL = .4 + s1; o.aR = .4 - s1; break;
      case "hop": o.dy = -ab * 4; o.sq = hit * .18; o.aL = o.aR = .3 + ab * 1.1; break;
      case "roof": o.dy = -ab * 1.2; o.sq = hit * .1; o.aL = o.aR = 1.25 + .3 * Math.sin(bp * TAU); break;
      case "sway": o.dx = s1 * 3; o.rot = s1 * .12; o.aL = .5 + .6 * s1; o.aR = .5 - .6 * s1; o.sq = hit * .08; break;
      case "spin": {
        const ph = (((bi % 4) + 4) % 4 === 3) ? bf : 0;
        Object.assign(o, spinView(ph));
        o.smear = ph > .1 && ph < .9 ? .5 : 0;
        o.smearDir = 0;
        o.dy = -Math.sin(ph * Math.PI) * 3 - ab;
        o.aL = o.aR = .6 + ph;
        o.sq = hit * .1;
        break;
      }
      case "wave": o.dy = -ab; o.aL = 1.1 + .5 * Math.sin(bp * TAU * 2); o.aR = -.2; o.sq = hit * .08; break;
      case "walk": o.walk = bp / 2; o.dy = -ab * .6; o.aL = .3 * s1; o.aR = -o.aL; break;
      case "run": o.walk = bp * 1.5; o.dy = -Math.abs(Math.sin(bp * TAU)); o.aL = .8 * Math.sin(bp * TAU * 1.5); o.aR = -o.aL; o.rot = -.08; break;
      case "idle": o.dy = -ab * .5; o.sq = hit * .05; break;
      case "stomp": o.dy = -Math.max(0, Math.sin(bp * TAU)) * 1.4; o.sq = hit * .2; o.rot = (bi % 2 ? 1 : -1) * .06 * hit; o.aL = o.aR = -.3 + hit * .9; break;
      case "shimmy": o.dx = Math.sin(bp * TAU * 2) * .6; o.rot = Math.sin(bp * TAU * 2) * .05; o.aL = .9 + .4 * Math.sin(bp * TAU * 2); o.aR = .9 - .4 * Math.sin(bp * TAU * 2); o.dy = -ab * .5; break;
      default: break;
    }
    return o;
  }

  function shotAt(t, list, duration) {
    if (!list || !list.length) throw new Error("shot list is empty");
    let i = 0;
    while (i + 1 < list.length && t >= list[i + 1][0]) i++;
    const t0 = list[i][0];
    const end = i + 1 < list.length ? list[i + 1][0] : (duration == null ? clock.duration : duration);
    return { index: i, name: list[i][1], local: t - t0, duration: end - t0, at: t };
  }

  function configure(options) {
    if (options) Object.assign(clock, options);
    return Object.assign({}, clock);
  }

  return {
    configure, feel, emotions, move, jump, take, turn, spinView, shotAt, onTwos, spring, kf,
    mixCol, tintCols, ease, easeOut, easeIn, backOut, clamp, lerp, seg, pulse, beatN, bpOf,
    PAL, TINT, MOVES, emotionNames: () => Object.keys(EMO),
  };
});
