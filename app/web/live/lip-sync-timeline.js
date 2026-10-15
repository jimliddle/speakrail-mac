/* Clock-based phoneme poses, independent of the renderer (also usable by a
 * future 3D blend-shape rig). No text-length or loudness timing estimates. */
(() => {
  "use strict";
  const rest = () => [1, ...Array(14).fill(0)];
  class LipSyncTimeline {
    constructor() { this.tracks = []; }
    clear() { this.tracks = []; }
    schedule(start, duration, cues) {
      if (!Number.isFinite(start) || !Number.isFinite(duration) || duration <= 0) return;
      const safe = (cues || []).filter(c => Number.isFinite(c.start) && Number.isFinite(c.end)
        && c.start >= 0 && c.end > c.start && c.end <= duration + 0.02 && Number.isInteger(c.pose) && c.pose >= 0 && c.pose < 15);
      this.tracks.push({ start, end: start + duration, cues: safe.sort((a, b) => a.start - b.start) });
    }
    sample(time, lead = 0.025) {
      this.tracks = this.tracks.filter(track => track.end >= time - 0.2);
      const track = this.tracks.find(track => time >= track.start && time < track.end);
      if (!track) return rest();
      const t = time - track.start + lead, cues = track.cues;
      const i = cues.findIndex(cue => t >= cue.start && t < cue.end);
      if (i < 0) return rest();
      const cue = cues[i], weights = Array(15).fill(0);
      weights[cue.pose] = 1;
      // Short overlap at actual phone boundaries gives coarticulation while
      // retaining rapid bilabial closures. There is no minimum-pose dwell time.
      for (const [a, b] of [[cues[i - 1], cue], [cue, cues[i + 1]]]) {
        if (!a || !b || b.start - a.end > 0.025 || a.pose === b.pose) continue;
        const edge = (a.end + b.start) / 2;
        const width = Math.min(0.035, (a.end - a.start) * 0.3, (b.end - b.start) * 0.3);
        if (Math.abs(t - edge) < width) {
          const p = (t - edge + width) / (width * 2), blend = p * p * (3 - 2 * p);
          weights.fill(0); weights[a.pose] = 1 - blend; weights[b.pose] = blend;
          break;
        }
      }
      return weights;
    }
  }
  if (typeof module !== "undefined") module.exports = LipSyncTimeline;
  else window.LipSyncTimeline = LipSyncTimeline;
})();
