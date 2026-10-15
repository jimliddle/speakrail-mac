const test = require('node:test');
const assert = require('node:assert/strict');
const Timeline = require('../app/web/live/lip-sync-timeline.js');
const pose = weights => weights.indexOf(Math.max(...weights));

test('phonemes follow scheduled audio time, including silence and final rest', () => {
  const timeline = new Timeline();
  timeline.schedule(10, 1, [
    { start: 0, end: 0.15, pose: 1 },
    { start: 0.15, end: 0.7, pose: 10 },
    { start: 0.7, end: 1, pose: 0 },
  ]);
  assert.equal(pose(timeline.sample(9.9, 0)), 0);
  assert.equal(pose(timeline.sample(10.05, 0)), 1);
  assert.equal(pose(timeline.sample(10.4, 0)), 10);
  assert.equal(pose(timeline.sample(10.9, 0)), 0);
  assert.equal(pose(timeline.sample(11.1, 0)), 0);
});

test('coarticulation has normalized weights and preserves short lip closures', () => {
  const timeline = new Timeline();
  timeline.schedule(0, 1, [
    { start: 0, end: 0.2, pose: 10 },
    { start: 0.2, end: 0.24, pose: 1 },
    { start: 0.24, end: 1, pose: 14 },
  ]);
  const edge = timeline.sample(0.2, 0);
  assert(Math.abs(edge[10] - 0.5) < 1e-10);
  assert(Math.abs(edge[1] - 0.5) < 1e-10);
  assert.equal(pose(timeline.sample(0.22, 0)), 1);
  for (let time = 0; time < 1; time += 0.005) {
    const weights = timeline.sample(time, 0);
    assert(Math.abs(weights.reduce((a, b) => a + b) - 1) < 1e-9);
    assert(weights.every(w => w >= 0 && w <= 1));
  }
});

test('interruption clears poses and unaligned audio stays at rest', () => {
  const timeline = new Timeline();
  timeline.schedule(0, 3, [{ start: 0, end: 3, pose: 10 }]);
  timeline.clear();
  assert.equal(pose(timeline.sample(1)), 0);
  timeline.schedule(4, 1, []);
  assert.equal(pose(timeline.sample(4.5)), 0);
});
