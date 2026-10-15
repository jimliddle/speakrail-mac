const test = require('node:test');
const assert = require('node:assert/strict');
const AvatarMotion = require('../app/web/live/avatar-motion.js');

function advance(motion, state, start, seconds, hz = 60) {
  let value;
  for (let i = 0; i <= seconds * hz; i++) value = motion.sample(start + i * 1000 / hz, state);
  return value;
}

test('idle breath and gaze stay restrained; listening settles with a distinct posture', () => {
  const motion = new AvatarMotion(() => .9);
  const idle = advance(motion, 'idle', 0, 8);
  assert(Math.abs(idle.gazeX) > .001);
  assert(Math.abs(idle.roll) < .009 && Math.abs(idle.scale - 1) < .003);
  const entry = motion.sample(8016, 'listening');
  assert(Math.abs(entry.roll - idle.roll) < .001, 'No jump on entry');
  const listening = advance(motion, 'listening', 8016, 6);
  assert(listening.attention > .99 && listening.scale > 1.009);
  assert(listening.roll > .015 && Math.abs(listening.gazeX) < .0003);
  const exit = motion.sample(14048, 'idle');
  assert(Math.abs(exit.roll - listening.roll) < .001, 'No jump on exit');
});

test('motion is frame-rate independent and does not leap after a tab suspension', () => {
  const a = new AvatarMotion(() => .5), b = new AvatarMotion(() => .5);
  const x = advance(a, 'listening', 0, 4, 30), y = advance(b, 'listening', 0, 4, 120);
  for (const key of Object.keys(x)) assert(Math.abs(x[key] - y[key]) < .00001, key);
  const resumed = a.sample(100000, 'listening');
  assert(Math.abs(resumed.roll - x.roll) < .001);
});

test('reduced motion and static pose previews reset all decorative movement', () => {
  const motion = new AvatarMotion(() => .9);
  advance(motion, 'listening', 0, 8);
  const still = motion.sample(8100, 'listening', false);
  assert.deepEqual(still, { x: 0, y: 0, roll: 0, scale: 1, gazeX: 0, gazeY: 0, attention: 0, thinking: 0, brow: 0 });
  assert.deepEqual(motion.sample(9000, 'idle', false), still);
});
