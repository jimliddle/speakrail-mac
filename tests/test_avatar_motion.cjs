const test = require('node:test');
const assert = require('node:assert/strict');
const AvatarMotion = require('../app/web/live/avatar-motion.js');

function advance(motion, state, start, seconds, hz = 60) {
  let value;
  for (let i = 0; i <= seconds * hz; i++) value = motion.sample(start + i * 1000 / hz, state);
  return value;
}

test('idle moves gently; listening returns all head angles to neutral', () => {
  const motion = new AvatarMotion(() => .9);
  const idle = advance(motion, 'idle', 0, 8);
  assert(Math.abs(idle.gazeX) > .001);
  assert(Math.abs(idle.roll) < .005 && Math.abs(idle.yaw) < .04);
  const entry = motion.sample(8016, 'listening');
  assert(Math.abs(entry.roll - idle.roll) < .001, 'No jump on entry');
  const listening = advance(motion, 'listening', 8016, 6);
  assert(listening.attention > .99);
  for (const key of ['pitch', 'yaw', 'roll']) assert(listening[key] === 0, key);
  assert(Math.abs(listening.gazeX) < .0003);
  const exit = motion.sample(14048, 'idle');
  assert(Math.abs(exit.roll - listening.roll) < .001, 'No jump on exit');
});

test('listening never acquires a tilt during a sustained hold', () => {
  const motion = new AvatarMotion(() => .9);
  advance(motion, 'thinking', 0, 4);
  advance(motion, 'listening', 4000, 2);
  for (let t = 6000; t < 66000; t += 16) {
    const value = motion.sample(t, 'listening');
    assert(value.pitch === 0 && value.yaw === 0 && value.roll === 0);
  }
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
  assert.deepEqual(still, { pitch: 0, yaw: 0, roll: 0, gazeX: 0, gazeY: 0, attention: 0, thinking: 0, brow: 0 });
  assert.deepEqual(motion.sample(9000, 'idle', false), still);
});
