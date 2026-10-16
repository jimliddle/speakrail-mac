/* Small state-driven motions, independent of speech timing and frame rate. */
(() => {
  const neutral = () => ({ pitch: 0, yaw: 0, roll: 0, gazeX: 0, gazeY: 0, attention: 0, thinking: 0, brow: 0 });
  class AvatarMotion {
    constructor(random = Math.random) {
      this.random = random;
      this.time = 0;
      this.last = null;
      this.attention = this.thinking = 0;
      this.gazeX = this.gazeY = this.targetX = this.targetY = 0;
      this.nextGaze = 2;
      this.output = neutral();
    }

    sample(timestamp, state, enabled = true) {
      // Resume gently after a background tab or a paused renderer.
      const dt = this.last == null ? 0 : Math.min(.1, Math.max(0, (timestamp - this.last) / 1000));
      this.last = timestamp;
      if (!enabled) {
        this.attention = this.thinking = this.gazeX = this.gazeY = 0;
        this.targetX = this.targetY = 0;
        this.nextGaze = this.time + 2;
        return this.output = neutral();
      }
      this.time += dt;
      const ease = 1 - Math.exp(-dt / .8);
      this.attention += ((state === "listening" ? 1 : 0) - this.attention) * ease;
      this.thinking += ((state === "thinking" ? 1 : 0) - this.thinking) * ease;
      if (this.time >= this.nextGaze) {
        this.targetX = (this.random() - .5) * .005;
        this.targetY = (this.random() - .5) * .002;
        this.nextGaze = this.time + 3 + this.random() * 3;
      }
      const focus = 1 - this.attention * .9;
      const gazeEase = 1 - Math.exp(-dt / .25);
      this.gazeX += (this.targetX * focus - this.gazeX) * gazeEase;
      this.gazeY += ((this.targetY * focus + this.thinking * .001) - this.gazeY) * gazeEase;
      const t = this.time, drift = Math.sin(t * .63) * .7 + Math.sin(t * .29) * .3;
      // Listening has no pose offset. Ease existing idle motion back to neutral,
      // then keep head angles exactly zero rather than leaving a residual lean.
      const headFreedom = Math.max(0, 1 - this.attention / .6);
      return this.output = {
        pitch: (.016 * Math.sin(t * .91) - .015 * this.thinking) * headFreedom,
        yaw: (.038 * drift + .02 * this.thinking) * headFreedom,
        roll: .004 * Math.sin(t * .43) * headFreedom,
        gazeX: this.gazeX, gazeY: this.gazeY,
        attention: this.attention, thinking: this.thinking,
        brow: .02 * (Math.sin(t * .77) + 1) + .1 * this.attention,
      };
    }
  }
  if (typeof module !== "undefined" && module.exports) module.exports = AvatarMotion;
  else window.AvatarMotion = AvatarMotion;
})();
