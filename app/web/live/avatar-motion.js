/* Small state-driven motions, independent of speech timing and frame rate. */
(() => {
  const neutral = () => ({ x: 0, y: 0, roll: 0, scale: 1, gazeX: 0, gazeY: 0, attention: 0, thinking: 0, brow: 0 });
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
      const t = this.time, breath = Math.sin(t * 1.13), drift = Math.sin(t * .47) * .7 + Math.sin(t * .21) * .3;
      return this.output = {
        x: .0014 * drift * (1 - this.attention * .65),
        y: .00065 * breath + .001 * this.attention,
        roll: .008 * drift * (1 - this.attention * .7) + .018 * this.attention - .012 * this.thinking,
        scale: 1 + .0025 * breath + .012 * this.attention,
        gazeX: this.gazeX, gazeY: this.gazeY,
        attention: this.attention, thinking: this.thinking,
        brow: .015 * (breath + 1) + .1 * this.attention,
      };
    }
  }
  if (typeof module !== "undefined" && module.exports) module.exports = AvatarMotion;
  else window.AvatarMotion = AvatarMotion;
})();
