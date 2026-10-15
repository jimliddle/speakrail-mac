/* Optional, local-only mesh portrait renderer. The approved contact sheet is
 * cropped in memory; no image service, microphone, or extra dependency is used.
 * Mouth weights come from aligned phoneme timestamps, never from loudness.
 */
(() => {
  "use strict";
  const artworkURL = new URL("assets/mesh-face/contact-sheet.png", document.currentScript.src);
  const POSES = [
    "Rest", "M / B / P", "F / V", "TH", "T / D", "K / G", "CH / SH / J", "S / Z",
    "N / L", "R", "A / AH", "E / EH", "I / EE", "O / OH", "U / OO", "Blink",
    "Listening", "Thinking", "Curious", "Smiling", "Laughing", "Surprised", "Concerned", "Reassuring",
  ];
  const STATE_POSE = { idle: 0, listening: 16, thinking: 17, error: 22 };
  const clamp = (n, low, high) => Math.max(low, Math.min(high, n));
  const surface = (width, height) => Object.assign(document.createElement("canvas"), { width, height });

  class MeshAvatar {
    static poses = POSES;

    constructor(onError) {
      this.onError = onError;
      this.ready = false;
      this.loading = null;
      this.pose = 0;
      this.previousPose = 0;
      this.changedAt = 0;
      this.nextBlink = 4000;
      this.blinkAt = null;
      this.reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
    }

    resetMouth() { this.pose = 0; this.previousPose = 0; this.changedAt = 0; }

    load() {
      if (this.loading) return this.loading;
      this.loading = new Promise((resolve) => {
        const image = new Image();
        image.onload = () => {
          this.prepare(image);
          this.ready = true;
          resolve(true);
        };
        image.onerror = () => {
          this.loading = null; // A later selection may retry a transient failure.
          this.onError();
          resolve(false);
        };
        image.src = artworkURL.href;
      });
      return this.loading;
    }

    prepare(image) {
      const cellW = image.naturalWidth / 4, cellH = image.naturalHeight / 6;
      // Remove the contact sheet's grid and the label underneath every portrait.
      this.width = Math.round(cellW * 0.969);
      this.height = Math.round(cellH * 0.875);
      const { width: w, height: h } = this;
      this.frames = POSES.map((_, i) => {
        const frame = surface(w, h);
        frame.getContext("2d").drawImage(image,
          (i % 4) * cellW + cellW * 0.016, Math.floor(i / 4) * cellH + cellH * 0.02,
          w, h, 0, 0, w, h);
        return frame;
      });
      // Change the lower face only during speech. Keeping hair, eyes and upper
      // mesh fixed avoids the head jitter in whole-frame contact-sheet playback.
      this.speechFrames = this.frames.slice(0, 15).map((frame) => {
        const composed = surface(w, h), c = composed.getContext("2d");
        c.drawImage(this.frames[0], 0, 0);
        c.drawImage(this.masked(frame, 0.5, 0.75, 0.28, 0.23), 0, 0);
        return composed;
      });
      this.blink = this.masked(this.frames[15], 0.5, 0.49, 0.37, 0.15);
    }

    masked(frame, x, y, rx, ry) {
      const { width: w, height: h } = this;
      const patch = surface(w, h), c = patch.getContext("2d");
      c.drawImage(frame, 0, 0);
      c.globalCompositeOperation = "destination-in";
      c.translate(x * w, y * h); c.scale(rx * w, ry * h);
      const mask = c.createRadialGradient(0, 0, 0, 0, 0, 1);
      mask.addColorStop(0, "#000"); mask.addColorStop(0.58, "#000"); mask.addColorStop(1, "#0000");
      c.fillStyle = mask;
      // Cover the entire image so destination-in also clears outside the mask.
      c.fillRect(-w, -h, w * 2, h * 2);
      return patch;
    }

    draw(ctx, t, w, h, { state = "idle", mouthWeights = null, previewPose = null } = {}) {
      if (!this.ready) return false;
      const speaking = state === "speaking";
      const requested = previewPose != null ? previewPose : speaking && mouthWeights ? mouthWeights.indexOf(Math.max(...mouthWeights))
        : ({ smiling: 19, curious: 18, reassuring: 23 }[state] ?? STATE_POSE[state] ?? 0);
      if (requested !== this.pose) {
        this.previousPose = this.pose; this.pose = requested; this.changedAt = t;
      }
      const reduced = this.reducedMotion.matches;
      const transition = reduced ? 1 : clamp((t - this.changedAt) / 180, 0, 1);
      const frame = (i) => i < 15 ? this.speechFrames[i] : this.frames[i];
      const breathe = reduced ? 1 : 1 + Math.sin(t * 0.0009) * 0.004;
      const width = Math.min(w * 0.88, h * 0.76, Math.max(60, h - 170) * this.width / this.height, 520) * breathe;
      const height = width * this.height / this.width;
      const x = (w - width) / 2;
      const y = Math.max(16, Math.min((h - height) / 2 - h * 0.06, h - height - 150));

      ctx.save();
      // Blend complete opaque frames with normalized weights, then screen the
      // result onto the page. This avoids double-strength wireframe lines.
      if (!this.blended) this.blended = surface(this.width, this.height);
      const blend = this.blended.getContext("2d");
      blend.globalAlpha = 1; blend.globalCompositeOperation = "source-over";
      blend.fillStyle = "#000"; blend.fillRect(0, 0, this.width, this.height);
      blend.globalCompositeOperation = "lighter";
      if (speaking && mouthWeights && previewPose == null) {
        mouthWeights.forEach((weight, i) => {
          if (weight > 0) { blend.globalAlpha = weight; blend.drawImage(this.speechFrames[i], 0, 0); }
        });
      } else {
        blend.globalAlpha = 1 - transition; blend.drawImage(frame(this.previousPose), 0, 0);
        blend.globalAlpha = transition; blend.drawImage(frame(this.pose), 0, 0);
      }
      blend.globalAlpha = 1; blend.globalCompositeOperation = "source-over";

      if (!reduced && previewPose == null) {
        if (this.blinkAt == null && t >= this.nextBlink) this.blinkAt = t;
        if (this.blinkAt != null) {
          const progress = (t - this.blinkAt) / 180;
          if (progress >= 1) { this.blinkAt = null; this.nextBlink = t + 3500 + Math.random() * 2500; }
          else {
            // The closed-eye patch must cover, rather than add light to, eyes.
            blend.globalAlpha = Math.sin(progress * Math.PI); blend.drawImage(this.blink, 0, 0);
            blend.globalAlpha = 1;
          }
        }
      }
      ctx.globalCompositeOperation = "screen";
      ctx.drawImage(this.blended, x, y, width, height);
      ctx.restore();
      return true;
    }
  }
  window.MeshAvatar = MeshAvatar;
})();
