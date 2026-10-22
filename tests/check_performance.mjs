import {createRequire} from "node:module";
import {fileURLToPath} from "node:url";
import path from "node:path";

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const P = require(path.join(here, "../skills/storytelling/codevideo/performance.js"));

function near(actual, expected, label) {
  if (Math.abs(actual - expected) > 1e-9) {
    throw new Error(`${label}: ${actual} != ${expected}`);
  }
}

const names = ["neutral", "happy", "excited", "laugh", "love", "shy", "proud", "smug", "relieved", "sad", "cry", "angry", "furious", "scared", "surprised", "confused", "thinking", "idea", "determined", "sleepy", "bored", "nervous", "suspicious", "disgusted", "dizzy", "cool", "starstruck", "ko", "playful", "mischief", "hopeful"];
P.configure({bpm: 120, offset: 0, duration: 8});
const got = P.emotionNames();
if (got.length !== 31 || names.some((name, i) => got[i] !== name)) {
  throw new Error("emotion list drifted: " + got.join(","));
}

const happy = P.feel("happy", 0);
if (happy.eyes !== "happy" || happy.mouth !== "smile" || happy.blush !== 0.3) throw new Error("happy face");
near(happy.dy, 0, "happy.dy");
near(happy.sq, 0.1, "happy.sq");
near(happy.aL, 0.4, "happy.aL");
near(happy.aR, 0.4, "happy.aR");
if (JSON.stringify(P.feel("happy", 0.5)) !== JSON.stringify(P.feel("happy", 0.5))) throw new Error("feel is not stable");
if (!Array.isArray(P.feel("confused", 0).eyes)) throw new Error("confused eyes");
if (P.feel("not-an-emotion", 0).emotion !== "neutral") throw new Error("unknown emotion");

const keys = [[0, "neutral"], [2, "happy"]];
near(P.emotions(1.95, keys).squint, 0.5, "anticipation squint");
if (P.emotions(1, keys).squint) throw new Error("squint away from the cut");
if (P.emotions(2, keys).emotion !== "happy") throw new Error("two-tuple keys");

const walk = P.move("walk", 0.5);
near(walk.walk, 0.5, "walk phase");
if (!P.MOVES.includes("mix")) throw new Error("moves");
const jump = P.jump(1.2, 1, 1.4, 3);
near(jump.dy, -3, "jump apex");
near(P.jump(0, 1, 1.4, 3).dy, 0, "jump before");
if (P.spring(0.2, 0.5) !== 0) throw new Error("spring before the kick");
if (P.spring(0.55, 0.5) === 0) throw new Error("spring after the kick");
near(P.onTwos(0.1), 1 / 12, "on twos");
const side = P.spinView(0.25);
if (side.view !== "side" || side.flip) throw new Error("spin view");

const shot = P.shotAt(2.5, [[0, "open"], [2, "turn"]], 4);
if (shot.index !== 1 || shot.name !== "turn") throw new Error("shot index");
near(shot.local, 0.5, "shot local");
near(shot.duration, 2, "shot duration");
console.log("performance ok");
